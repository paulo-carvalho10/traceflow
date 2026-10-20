"""A ingestão: a porta de entrada dos spans.

Ela é fina de propósito: confere o que chegou, enfileira e responde em milissegundos.
Não fala com o banco, não guarda estado além de contadores, e escala só subindo mais cópias.

    POST /v1/traces   OTLP/HTTP, protobuf ou JSON, gzip opcional
    GET  /healthz     a ingestão está de pé e o Redis responde

A ingestão NÃO é instrumentada com OpenTelemetry: os spans dela entrariam nela mesma,
e cada lote recebido geraria mais um lote para receber.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field

import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from traceflow import otlp
from traceflow.config import Settings, setup_logging
from traceflow.config import redis_client as make_redis_client
from traceflow.streams import SPANS_STREAM, SpanBatch

log = logging.getLogger("traceflow.ingest")


@dataclass
class IngestState:
    """O que a ingestão sabe: o tamanho da fila (atualizado em segundo plano) e contadores."""

    backlog: int = 0
    spans_accepted: int = 0
    batches_accepted: int = 0
    rejected: Counter[str] = field(default_factory=Counter)


def create_app(settings: Settings | None = None, redis_client: redis.Redis | None = None) -> FastAPI:
    settings = settings or Settings()
    owns_client = redis_client is None
    client = redis_client or make_redis_client(settings.redis_url)
    state = IngestState()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [
            asyncio.create_task(refresh_backlog(client, state, settings.backlog_refresh_s)),
            asyncio.create_task(report_stats(state, settings.stats_every_s)),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            if owns_client:
                await client.aclose()

    app = FastAPI(title="TraceFlow · ingestão", lifespan=lifespan)
    app.state.ingest = state

    def reject(reason: str, status: int, message: str, retry: bool = False) -> Response:
        state.rejected[reason] += 1
        headers = {"Retry-After": str(settings.retry_after_s)} if retry else None
        return PlainTextResponse(message, status_code=status, headers=headers)

    @app.post("/v1/traces")
    async def export_traces(request: Request) -> Response:
        content_type = otlp.media_type(request.headers.get("content-type"))
        if content_type not in otlp.SUPPORTED:
            return reject("tipo", 415, f"Content-Type {content_type or '(vazio)'} não suportado")

        try:
            raw = await read_body(request, settings.max_body_bytes)
            body = otlp.decompress(raw, request.headers.get("content-encoding"), settings.max_body_bytes)
            export = otlp.parse_request(body, content_type)
        except otlp.OtlpError as exc:
            return reject(type(exc).__name__, exc.status_code, str(exc))

        ok = Response(otlp.success_response(content_type), media_type=content_type)
        spans = otlp.count_spans(export)
        if spans == 0:
            return ok

        # Contrapressão: com a fila cheia, pedir para esperar é melhor que aceitar e cair sem memória.
        # Os exportadores do OpenTelemetry entendem 503 + Retry-After e tentam de novo depois.
        if state.backlog >= settings.max_backlog:
            return reject("fila_cheia", 503, "fila cheia, tente de novo depois", retry=True)

        batch = SpanBatch(
            project_id=settings.default_project_id,
            received_at_ms=time.time_ns() // 1_000_000,
            span_count=spans,
            # protobuf chega pronto; JSON é convertido, para o processador só conhecer um formato
            payload=body if content_type == otlp.PROTOBUF else export.SerializeToString(),
        )
        try:
            await client.xadd(
                SPANS_STREAM,
                batch.to_fields(),  # type: ignore[arg-type]
                maxlen=settings.max_backlog * 2,  # teto de segurança, caso o freio acima falhe
                approximate=True,
            )
        except redis.RedisError as exc:
            log.warning("não consegui enfileirar no Redis: %s", exc)
            return reject("redis", 503, "fila indisponível, tente de novo depois", retry=True)

        state.batches_accepted += 1
        state.spans_accepted += spans
        return ok

    @app.get("/healthz")
    async def healthz() -> Response:
        try:
            await client.ping()
        except redis.RedisError:
            return PlainTextResponse("redis indisponível", status_code=503)
        return PlainTextResponse("ok")

    return app


async def read_body(request: Request, limit: int) -> bytes:
    """Lê o corpo em pedaços e para assim que passar do limite, sem carregar o resto na memória."""
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            raise otlp.InvalidPayload("Content-Length inválido")
        if int(declared) > limit:
            raise otlp.PayloadTooLarge(f"corpo de {declared} bytes passa do limite de {limit}")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise otlp.PayloadTooLarge(f"corpo passa do limite de {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def refresh_backlog(client: redis.Redis, state: IngestState, every_s: float) -> None:
    """Atualiza o tamanho da fila em segundo plano.

    Perguntar ao Redis em toda requisição dobraria as idas ao Redis. Um valor com até 250 ms
    de atraso é suficiente para um freio: a fila não enche em 250 ms.
    """
    warned = False
    while True:
        try:
            state.backlog = await client.xlen(SPANS_STREAM)
            warned = False
        except redis.RedisError as exc:
            if not warned:
                log.warning("não consegui ler o tamanho da fila: %s", exc)
                warned = True
        await asyncio.sleep(every_s)


async def report_stats(state: IngestState, every_s: float) -> None:
    last_spans, last_at = state.spans_accepted, time.monotonic()
    while True:
        await asyncio.sleep(every_s)
        now = time.monotonic()
        rate = (state.spans_accepted - last_spans) / (now - last_at)
        rejected = " ".join(f"{k}={v}" for k, v in sorted(state.rejected.items())) or "nenhuma"
        log.info(
            "%.0f spans/s aceitos, fila=%d lotes, recusas: %s, total aceito=%d",
            rate,
            state.backlog,
            rejected,
            state.spans_accepted,
        )
        last_spans, last_at = state.spans_accepted, now


def main() -> None:
    setup_logging()
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.ingest_host,
        port=settings.ingest_port,
        access_log=False,
    )


if __name__ == "__main__":
    main()

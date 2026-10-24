"""A ingestão: a porta de entrada dos spans.

Ela é fina de propósito: confere a chave e o que chegou, enfileira e responde em milissegundos.
Do banco ela só lê chaves, com cache de 60 s; não guarda estado além disso e de contadores,
e escala só subindo mais cópias.

    POST /v1/traces   OTLP/HTTP, protobuf ou JSON, gzip opcional, com Authorization: Bearer tf_...
    GET  /healthz     a ingestão está de pé e o Redis responde

As métricas (Prometheus) ficam numa porta interna, em GET /metrics (traceflow.prometheus).

A ingestão NÃO é instrumentada com OpenTelemetry: os spans dela entrariam nela mesma,
e cada lote recebido geraria mais um lote para receber.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field

import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.metrics_core import Metric

from traceflow import otlp
from traceflow.config import Settings, setup_logging
from traceflow.config import redis_client as make_redis_client
from traceflow.ingest.keys import KeyUnavailable, KeyVerifier, PostgresKeyLookup
from traceflow.prometheus import LATENCY_BUCKETS, Reading, new_registry, serve
from traceflow.streams import SPANS_STREAM, SpanBatch

log = logging.getLogger("traceflow.ingest")


@dataclass
class IngestState:
    """O que a ingestão sabe: o tamanho da fila (atualizado em segundo plano) e contadores."""

    backlog: int = 0
    queue_age_s: float = 0.0
    spans_accepted: int = 0
    batches_accepted: int = 0
    rejected: Counter[str] = field(default_factory=Counter)

    def metrics(self) -> Iterator[Metric]:
        yield CounterMetricFamily(
            "traceflow_ingest_spans_accepted", "Spans aceitos e enfileirados", value=self.spans_accepted
        )
        yield CounterMetricFamily(
            "traceflow_ingest_batches_accepted", "Lotes aceitos e enfileirados", value=self.batches_accepted
        )
        rejected = CounterMetricFamily(
            "traceflow_ingest_rejected", "Lotes recusados, por motivo", labels=["reason"]
        )
        for reason, count in sorted(dict(self.rejected).items()):  # dict(): cópia de uma vez só
            rejected.add_metric([reason], count)
        yield rejected
        yield GaugeMetricFamily(
            "traceflow_ingest_backlog_batches",
            "Lotes esperando o processador",
            value=self.backlog,
        )
        yield GaugeMetricFamily(
            "traceflow_ingest_queue_age_seconds",
            "Há quanto tempo o lote mais antigo da fila espera; o freio da contrapressão",
            value=self.queue_age_s,
        )


def create_app(
    settings: Settings | None = None,
    redis_client: redis.Redis | None = None,
    keys: KeyVerifier | None = None,
) -> FastAPI:
    settings = settings or Settings()
    owns_client = redis_client is None
    client = redis_client or make_redis_client(settings.redis_url)
    state = IngestState()
    registry = new_registry()
    registry.register(Reading(state.metrics))
    request_seconds = Histogram(
        "traceflow_ingest_request_seconds",
        "Quanto leva cada POST /v1/traces, recusas incluídas",
        buckets=LATENCY_BUCKETS,
        registry=registry,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        close_metrics = serve(registry, settings.metrics_port)
        lookup = None
        if app.state.keys is None:
            lookup = await PostgresKeyLookup.connect(settings.database_url)
            app.state.keys = KeyVerifier(
                lookup, ttl_s=settings.key_cache_ttl_s, negative_ttl_s=settings.key_negative_cache_ttl_s
            )
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
            if lookup is not None:
                await lookup.close()
            close_metrics()

    app = FastAPI(title="TraceFlow · ingestão", lifespan=lifespan)
    app.state.ingest = state
    app.state.keys = keys
    app.state.registry = registry

    def reject(reason: str, status: int, message: str, retry: bool = False) -> Response:
        state.rejected[reason] += 1
        headers = {"Retry-After": str(settings.retry_after_s)} if retry else None
        return PlainTextResponse(message, status_code=status, headers=headers)

    @app.post("/v1/traces")
    async def export_traces(request: Request) -> Response:
        started = time.perf_counter()
        try:
            return await receive(request)
        finally:
            request_seconds.observe(time.perf_counter() - started)

    async def receive(request: Request) -> Response:
        # A chave vem antes de tudo: sem ela, nem o corpo é lido.
        verifier: KeyVerifier = request.app.state.keys
        try:
            project_id = await verifier.project_for(request.headers.get("authorization"))
        except KeyUnavailable:
            return reject("chave_indisponivel", 503, "não deu para conferir a chave agora", retry=True)
        if project_id is None:
            return reject("chave", 401, "chave de ingestão ausente, inválida ou revogada")

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

        # Contrapressão: com o processador atrasado, pedir para esperar é melhor que aceitar e cair
        # sem memória. O freio é a idade do lote mais antigo, que vale para lotes de 1 ou de 200
        # spans (D65); a contagem de lotes fica como segunda trava. Os exportadores do
        # OpenTelemetry entendem 503 + Retry-After e tentam de novo depois.
        if state.queue_age_s > settings.max_queue_age_s or state.backlog >= settings.max_backlog:
            return reject("fila_cheia", 503, "fila atrasada, tente de novo depois", retry=True)

        batch = SpanBatch(
            project_id=project_id,
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


async def read_queue(client: redis.Redis) -> tuple[int, float]:
    """O tamanho da fila e a idade, em segundos, do lote mais antigo que ainda espera.

    O id de uma entrada do stream começa pelo horário em que ela entrou, em ms, no relógio do
    Redis. Comparado com o TIME do mesmo Redis, dá a idade sem depender do relógio da ingestão.
    """
    pipe = client.pipeline(transaction=False)
    pipe.xlen(SPANS_STREAM)
    pipe.xrange(SPANS_STREAM, count=1)  # o processador apaga o que já tratou: o primeiro é o mais velho
    pipe.time()
    length, oldest, (seconds, micros) = await pipe.execute()
    if not oldest:
        return int(length), 0.0
    entered_ms = int(oldest[0][0].split(b"-")[0])
    return int(length), max(0.0, seconds + micros / 1e6 - entered_ms / 1000)


async def refresh_backlog(client: redis.Redis, state: IngestState, every_s: float) -> None:
    """Atualiza o tamanho e a idade da fila em segundo plano.

    Perguntar ao Redis em toda requisição dobraria as idas ao Redis. Um valor com até 250 ms
    de atraso é suficiente para um freio: a fila não envelhece 30 s em 250 ms.
    """
    warned = False
    while True:
        try:
            state.backlog, state.queue_age_s = await read_queue(client)
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

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from helpers import JSON_EXAMPLE, export_request
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from test_keys import AUTH, FakeLookup

from traceflow import otlp
from traceflow.config import Settings, redis_client
from traceflow.ingest.app import IngestState, create_app, read_queue
from traceflow.ingest.keys import KeyVerifier
from traceflow.streams import SPANS_STREAM, SpanBatch

WITH_KEY = {"authorization": AUTH}  # a chave do FakeLookup, do projeto 7
PROTOBUF = {**WITH_KEY, "content-type": otlp.PROTOBUF}


def app_for(
    redis_client: object, settings: Settings | None = None, lookup: FakeLookup | None = None
) -> FastAPI:
    keys = KeyVerifier(lookup or FakeLookup(), ttl_s=60, negative_ttl_s=10)
    return create_app(settings or Settings(), redis_client, keys)  # type: ignore[arg-type]


@pytest.fixture
async def fake_redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    yield client
    await client.aclose()


def client_for(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ingest")  # type: ignore[arg-type]


async def queued(fake: FakeAsyncRedis) -> list[SpanBatch]:
    entries = cast(list[tuple[bytes, dict[bytes, bytes]]], await fake.xrange(SPANS_STREAM))
    return [SpanBatch.from_fields(fields) for _, fields in entries]


async def test_protobuf_entra_na_fila_intacto(fake_redis: FakeAsyncRedis) -> None:
    app = app_for(fake_redis)
    body = export_request({"orders": 2, "payments": 3}).SerializeToString()
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=PROTOBUF)
    assert response.status_code == 200
    assert response.headers["content-type"] == otlp.PROTOBUF
    [batch] = await queued(fake_redis)
    assert batch.payload == body
    assert batch.span_count == 5
    assert batch.project_id == 7
    state: IngestState = app.state.ingest
    assert (state.batches_accepted, state.spans_accepted) == (1, 5)


async def test_json_vira_protobuf_na_fila(fake_redis: FakeAsyncRedis) -> None:
    app = app_for(fake_redis, Settings())
    async with client_for(app) as c:
        response = await c.post("/v1/traces", json=JSON_EXAMPLE, headers=WITH_KEY)
    assert response.status_code == 200
    assert response.json() == {}
    [batch] = await queued(fake_redis)
    decoded = ExportTraceServiceRequest.FromString(batch.payload)
    assert decoded.resource_spans[0].scope_spans[0].spans[0].name == "POST /orders"


async def test_gzip_e_aceito(fake_redis: FakeAsyncRedis) -> None:
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(app_for(fake_redis, Settings())) as c:
        response = await c.post(
            "/v1/traces", content=gzip.compress(body), headers={**PROTOBUF, "content-encoding": "gzip"}
        )
    assert response.status_code == 200
    [batch] = await queued(fake_redis)
    assert batch.payload == body  # na fila vai descomprimido


async def test_lote_vazio_responde_ok_sem_enfileirar(fake_redis: FakeAsyncRedis) -> None:
    async with client_for(app_for(fake_redis, Settings())) as c:
        response = await c.post("/v1/traces", content=b"", headers=PROTOBUF)
    assert response.status_code == 200
    assert await fake_redis.xlen(SPANS_STREAM) == 0


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({**WITH_KEY, "content-type": "text/plain"}, b"oi", 415),
        (PROTOBUF, b"\xff\xff\xff lixo", 400),
        ({**WITH_KEY, "content-type": otlp.JSON}, json.dumps({"resourceSpans": 1}).encode(), 400),
        ({**PROTOBUF, "content-encoding": "br"}, b"abc", 415),
    ],
    ids=["tipo", "protobuf-invalido", "json-invalido", "compressao-desconhecida"],
)
async def test_requisicao_ruim_e_recusada_sem_enfileirar(
    fake_redis: FakeAsyncRedis, headers: dict[str, str], body: bytes, status: int
) -> None:
    app = app_for(fake_redis, Settings())
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=headers)
    assert response.status_code == status
    assert await fake_redis.xlen(SPANS_STREAM) == 0
    assert sum(app.state.ingest.rejected.values()) == 1


async def test_corpo_grande_demais_e_recusado(fake_redis: FakeAsyncRedis) -> None:
    app = app_for(fake_redis, Settings(max_body_bytes=1000))
    body = export_request({"orders": 50}).SerializeToString()
    assert len(body) > 1000
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=PROTOBUF)
    assert response.status_code == 413


async def test_fila_cheia_pede_para_tentar_depois(fake_redis: FakeAsyncRedis) -> None:
    app = app_for(fake_redis, Settings(max_backlog=100, retry_after_s=7))
    app.state.ingest.backlog = 100  # o que a tarefa de fundo teria lido do Redis
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=PROTOBUF)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "7"
    assert await fake_redis.xlen(SPANS_STREAM) == 0


async def test_fila_atrasada_freia_mesmo_com_poucos_lotes(fake_redis: FakeAsyncRedis) -> None:
    # 10 lotes de 200 spans esperando há 31 s: poucos lotes, muito atraso
    app = app_for(fake_redis, Settings(max_queue_age_s=30))
    app.state.ingest.backlog, app.state.ingest.queue_age_s = 10, 31.0
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(app) as c:
        assert (await c.post("/v1/traces", content=body, headers=PROTOBUF)).status_code == 503
        app.state.ingest.queue_age_s = 29.0
        assert (await c.post("/v1/traces", content=body, headers=PROTOBUF)).status_code == 200


async def test_idade_da_fila_vem_do_lote_mais_antigo(fake_redis: FakeAsyncRedis) -> None:
    assert await read_queue(fake_redis) == (0, 0.0)  # fila vazia: nada esperando
    seconds, _ = await fake_redis.time()
    await fake_redis.xadd(SPANS_STREAM, {"x": "1"}, id=f"{(seconds - 40) * 1000}-0")
    await fake_redis.xadd(SPANS_STREAM, {"x": "2"}, id=f"{(seconds - 5) * 1000}-0")
    length, age = await read_queue(fake_redis)
    assert length == 2
    assert 40 <= age < 42


async def test_redis_fora_do_ar_pede_para_tentar_depois() -> None:
    dead = redis_client("redis://localhost:1/0", retries=0)  # ninguém escuta na porta 1
    app = app_for(dead, Settings())
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=PROTOBUF)
        health = await c.get("/healthz")
    assert response.status_code == 503
    assert "retry-after" in response.headers
    assert health.status_code == 503
    await dead.aclose()


async def test_sem_chave_e_401_e_nada_entra_na_fila(fake_redis: FakeAsyncRedis) -> None:
    app = app_for(fake_redis)
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(app) as c:
        sem = await c.post("/v1/traces", content=body, headers={"content-type": otlp.PROTOBUF})
        errada = await c.post(
            "/v1/traces", content=body, headers={**PROTOBUF, "authorization": "Bearer tf_x"}
        )
    assert (sem.status_code, errada.status_code) == (401, 401)
    assert "retry-after" not in sem.headers  # 401: não adianta tentar de novo
    assert await fake_redis.xlen(SPANS_STREAM) == 0
    assert app.state.ingest.rejected["chave"] == 2


async def test_banco_fora_sem_cache_e_503_para_o_exportador_tentar_depois(fake_redis: FakeAsyncRedis) -> None:
    lookup = FakeLookup()
    lookup.down = True
    app = app_for(fake_redis, lookup=lookup)
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=PROTOBUF)
    assert response.status_code == 503 and "retry-after" in response.headers

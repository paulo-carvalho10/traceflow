from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from helpers import JSON_EXAMPLE, export_request
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from traceflow import otlp
from traceflow.config import Settings, redis_client
from traceflow.ingest.app import IngestState, create_app
from traceflow.streams import SPANS_STREAM, SpanBatch

PROTOBUF = {"content-type": otlp.PROTOBUF}


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
    app = create_app(Settings(default_project_id=7), fake_redis)
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
    app = create_app(Settings(), fake_redis)
    async with client_for(app) as c:
        response = await c.post("/v1/traces", json=JSON_EXAMPLE)
    assert response.status_code == 200
    assert response.json() == {}
    [batch] = await queued(fake_redis)
    decoded = ExportTraceServiceRequest.FromString(batch.payload)
    assert decoded.resource_spans[0].scope_spans[0].spans[0].name == "POST /orders"


async def test_gzip_e_aceito(fake_redis: FakeAsyncRedis) -> None:
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(create_app(Settings(), fake_redis)) as c:
        response = await c.post(
            "/v1/traces", content=gzip.compress(body), headers={**PROTOBUF, "content-encoding": "gzip"}
        )
    assert response.status_code == 200
    [batch] = await queued(fake_redis)
    assert batch.payload == body  # na fila vai descomprimido


async def test_lote_vazio_responde_ok_sem_enfileirar(fake_redis: FakeAsyncRedis) -> None:
    async with client_for(create_app(Settings(), fake_redis)) as c:
        response = await c.post("/v1/traces", content=b"", headers=PROTOBUF)
    assert response.status_code == 200
    assert await fake_redis.xlen(SPANS_STREAM) == 0


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({"content-type": "text/plain"}, b"oi", 415),
        (PROTOBUF, b"\xff\xff\xff lixo", 400),
        ({"content-type": otlp.JSON}, json.dumps({"resourceSpans": 1}).encode(), 400),
        ({**PROTOBUF, "content-encoding": "br"}, b"abc", 415),
    ],
    ids=["tipo", "protobuf-invalido", "json-invalido", "compressao-desconhecida"],
)
async def test_requisicao_ruim_e_recusada_sem_enfileirar(
    fake_redis: FakeAsyncRedis, headers: dict[str, str], body: bytes, status: int
) -> None:
    app = create_app(Settings(), fake_redis)
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=headers)
    assert response.status_code == status
    assert await fake_redis.xlen(SPANS_STREAM) == 0
    assert sum(app.state.ingest.rejected.values()) == 1


async def test_corpo_grande_demais_e_recusado(fake_redis: FakeAsyncRedis) -> None:
    app = create_app(Settings(max_body_bytes=1000), fake_redis)
    body = export_request({"orders": 50}).SerializeToString()
    assert len(body) > 1000
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=PROTOBUF)
    assert response.status_code == 413


async def test_fila_cheia_pede_para_tentar_depois(fake_redis: FakeAsyncRedis) -> None:
    app = create_app(Settings(max_backlog=100, retry_after_s=7), fake_redis)
    app.state.ingest.backlog = 100  # o que a tarefa de fundo teria lido do Redis
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=PROTOBUF)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "7"
    assert await fake_redis.xlen(SPANS_STREAM) == 0


async def test_redis_fora_do_ar_pede_para_tentar_depois() -> None:
    dead = redis_client("redis://localhost:1/0", retries=0)  # ninguém escuta na porta 1
    app = create_app(Settings(), dead)
    body = export_request({"orders": 1}).SerializeToString()
    async with client_for(app) as c:
        response = await c.post("/v1/traces", content=body, headers=PROTOBUF)
        health = await c.get("/healthz")
    assert response.status_code == 503
    assert "retry-after" in response.headers
    assert health.status_code == 503
    await dead.aclose()

"""As métricas no formato do Prometheus: o que cada processo expõe, e o GET /metrics de verdade."""

from __future__ import annotations

import socket
import urllib.request
from collections.abc import AsyncIterator

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from helpers import export_request
from test_ingest import PROTOBUF, app_for
from test_processor import FakeStore, enqueue, processor

from traceflow.api.app import create_app as create_api
from traceflow.api.live import Subscriber
from traceflow.config import Settings
from traceflow.prometheus import new_registry, serve


@pytest.fixture
async def fake_redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    yield client
    await client.aclose()


def client_for(app: object, base: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base)  # type: ignore[arg-type]


async def test_ingestao_conta_aceitos_recusas_e_cronometra(fake_redis: FakeAsyncRedis) -> None:
    app = app_for(fake_redis)
    body = export_request({"orders": 2, "payments": 3}).SerializeToString()
    async with client_for(app, "http://ingest") as c:
        assert (await c.post("/v1/traces", content=body, headers=PROTOBUF)).status_code == 200
        assert (
            await c.post("/v1/traces", content=body, headers={"content-type": PROTOBUF["content-type"]})
        ).status_code == 401
    value = app.state.registry.get_sample_value
    assert value("traceflow_ingest_spans_accepted_total") == 5
    assert value("traceflow_ingest_batches_accepted_total") == 1
    assert value("traceflow_ingest_rejected_total", {"reason": "chave"}) == 1
    assert value("traceflow_ingest_request_seconds_count") == 2  # a recusa também conta no tempo


async def test_processador_mede_o_atraso_de_cada_lote(fake_redis: FakeAsyncRedis) -> None:
    p = processor(fake_redis, FakeStore())
    await p.ensure_group()
    await enqueue(fake_redis, 3)
    await enqueue(fake_redis, 2)
    await p.handle(await p.read(">"))
    value = p.registry.get_sample_value
    assert value("traceflow_processor_spans_written_total") == 5
    assert value("traceflow_processor_batches_total") == 2
    # os lotes chegaram na ingestão 50 ms antes do "agora" do processador
    assert value("traceflow_processor_lag_seconds_count") == 2
    assert value("traceflow_processor_lag_seconds_sum") == pytest.approx(0.1)
    assert value("traceflow_processor_lag_seconds_bucket", {"le": "0.05"}) == 2
    assert value("traceflow_processor_write_seconds_count") == 1
    assert value("traceflow_incidents_open") == 0


async def test_api_conta_pelo_molde_da_rota_e_nao_pelo_id(fake_redis: FakeAsyncRedis) -> None:
    app = create_api(Settings(), fake_redis)
    async with client_for(app, "http://api") as c:
        assert (await c.get("/api/projects/42/traces")).status_code == 401
        assert (await c.get("/api/projects/43/traces")).status_code == 401
        assert (await c.get("/nao-existe")).status_code == 404
    value = app.state.registry.get_sample_value
    route = "/api/projects/{project_id}/traces"
    assert value("traceflow_api_requests_total", {"method": "GET", "route": route, "status": "401"}) == 2
    assert value("traceflow_api_requests_total", {"method": "GET", "route": "sem rota", "status": "404"}) == 1
    assert value("traceflow_api_request_seconds_count", {"method": "GET", "route": route}) == 2

    hub = app.state.live_hub
    hub.subscribe(Subscriber(), (1, "demo"))
    hub.subscribe(Subscriber(), (1, "demo"))
    assert value("traceflow_api_live_tabs") == 2


def test_get_metrics_responde_na_porta_interna() -> None:
    registry = new_registry()
    with socket.socket() as s:  # uma porta livre
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    close = serve(registry, port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as response:
            text = response.read().decode()
    finally:
        close()
    assert "python_gc_objects_collected_total" in text  # o coletor do Python vem junto
    assert serve(registry, None)() is None  # sem porta, não abre nada


async def test_producao_nao_sobe_com_o_segredo_de_desenvolvimento(fake_redis: FakeAsyncRedis) -> None:
    # cookie só por HTTPS é sinal de produção; o segredo padrão está no git: qualquer um forjaria sessões
    app = create_api(Settings(cookie_secure=True), fake_redis)
    with pytest.raises(RuntimeError, match="TRACEFLOW_JWT_SECRET"):
        async with app.router.lifespan_context(app):
            pass

"""O mapa de um período passado (banco de teste), e a mesma regra de falha que o ao vivo."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from test_api_traces import row

from traceflow.api.app import create_app
from traceflow.config import Settings
from traceflow.live.aggregator import LiveAggregator
from traceflow.live.topology import AddressBook
from traceflow.normalize import SpanRow
from traceflow.storage import SpanStore

pytestmark = pytest.mark.db

# um minuto redondo que já passou: o histórico não mostra os últimos segundos (SETTLE)
NOW = (datetime.now(UTC) - timedelta(minutes=1)).replace(second=0, microsecond=0)


@pytest.fixture
async def visitor(clean_db: str) -> AsyncIterator[httpx.AsyncClient]:
    redis = FakeAsyncRedis()
    app: FastAPI = create_app(Settings(database_url=clean_db), redis)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        await c.post("/api/auth/demo")
        yield c
    await redis.aclose()


def purchase(i: int, bank_code: int | None, bank_status: str = "unset") -> list[SpanRow]:
    """gateway (entrada) → orders:8000 (orders) → bank:443 (externo, sem spans)."""
    trace, start = f"{i:032x}", NOW - timedelta(minutes=10, seconds=i)
    return [
        row(trace, "a" * 16, None, start, 100),
        row(trace, "b" * 16, "a" * 16, start, 90, kind="client", peer_address="orders:8000"),
        row(trace, "c" * 16, "b" * 16, start, 80, service="orders"),
        row(trace, "d" * 16, "c" * 16, start, 60, service="orders", kind="client", peer_address="bank:443",
            http_status_code=bank_code, status=bank_status),
    ]  # fmt: skip


ROWS = (
    [r for i in range(6) for r in purchase(i, 201)]
    + [r for i in range(6, 8) for r in purchase(i, 402, "error")]  # cartão recusado: não é falha
    + [r for i in range(8, 10) for r in purchase(i, None, "error")]  # o banco não respondeu: é falha
)


async def store(dsn: str) -> None:
    db = await SpanStore.connect(dsn)
    await db.insert(ROWS)
    await db.upsert_addresses([(1, "demo", "orders:8000", "orders", NOW)])  # o que o processador aprendeu
    await db.close()


async def test_mapa_do_periodo_com_nomes_nos_virtuais_e_entrada(
    visitor: httpx.AsyncClient, clean_db: str
) -> None:
    await store(clean_db)
    since, until = NOW - timedelta(minutes=30), NOW
    body = (
        await visitor.get(
            "/api/projects/1/map",
            params={"environment": "demo", "since": since.isoformat(), "until": until.isoformat()},
        )
    ).json()
    services = {s["name"]: s for s in body["services"]}
    assert services["gateway"]["entry_rps"] == pytest.approx(10 / 1800)  # 10 compras em 30 min
    assert services["orders"]["entry_rps"] == 0
    edges = {(e["source"], e["target"]): e for e in body["edges"]}
    assert set(edges) == {("gateway", "orders"), ("orders", "bank:443")}
    assert edges[("gateway", "orders")]["virtual"] is False and edges[("gateway", "orders")]["requests"] == 10
    bank = edges[("orders", "bank:443")]
    assert bank["virtual"] is True and bank["error_rate"] == pytest.approx(0.2)  # 2 sem resposta em 10


async def test_historico_e_ao_vivo_contam_falha_do_mesmo_jeito(
    visitor: httpx.AsyncClient, clean_db: str
) -> None:
    await store(clean_db)
    history = (
        await visitor.get(
            "/api/projects/1/map",
            params={
                "environment": "demo",
                "since": (NOW - timedelta(hours=1)).isoformat(),
                "until": NOW.isoformat(),
            },
        )
    ).json()["edges"]
    # os mesmos spans, como se estivessem chegando agora, pelo agregador ao vivo
    now = NOW.timestamp()
    recent = [
        SpanRow(**{**r.__dict__, "start_time": datetime.fromtimestamp(now - 8, tz=UTC)})  # dentro da janela
        for r in ROWS
    ]
    agg, book = LiveAggregator(), AddressBook()
    agg.add(recent, now)
    book.observe(recent, now)
    [snap] = agg.snapshots(now, book.resolve).values()
    live = {(e["source"], e["target"]): e["error_rate"] for e in snap["edges"]}
    assert live == {(e["source"], e["target"]): pytest.approx(e["error_rate"]) for e in history}


async def test_mapa_pede_o_ambiente_e_nao_mostra_projeto_alheio(visitor: httpx.AsyncClient) -> None:
    assert (await visitor.get("/api/projects/1/map")).status_code == 422
    assert (await visitor.get("/api/projects/999/map", params={"environment": "demo"})).status_code == 404

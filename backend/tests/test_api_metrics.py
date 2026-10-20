"""O histórico de um serviço, as rotas dele e o filtro "passou pelo serviço" (banco de teste)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from test_api_traces import checkout, row, store_rows

from traceflow.api.app import create_app
from traceflow.api.metrics import step_for
from traceflow.config import Settings

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


def test_passo_do_grafico_da_uns_60_pontos() -> None:
    assert step_for(timedelta(hours=1)) == 60
    assert step_for(timedelta(hours=6)) == 300
    assert step_for(timedelta(hours=24)) == 1800
    assert step_for(timedelta(days=3)) == 3600


async def test_serie_por_minuto_com_buracos_preenchidos(visitor: httpx.AsyncClient, clean_db: str) -> None:
    rows = []
    # 30 min atrás: 6 requisições, 2 com erro; 10 min atrás: 3; nada entre elas
    for i in range(6):
        trace = f"{i:032x}"
        rows.append(
            row(
                trace,
                "a" * 16,
                None,
                NOW - timedelta(minutes=30),
                100 + i,
                status="error" if i < 2 else "unset",
            )
        )
    for i in range(3):
        rows.append(row(f"{100 + i:032x}", "a" * 16, None, NOW - timedelta(minutes=10), 50))
    await store_rows(clean_db, rows)

    body = (
        await visitor.get(
            "/api/projects/1/services/gateway/metrics",
            params={"since": (NOW - timedelta(hours=1)).isoformat(), "until": NOW.isoformat()},
        )
    ).json()
    assert body["step_seconds"] == 60
    points = body["points"]
    assert len(points) == 60  # um por minuto, inclusive os vazios (gapfill)
    by_minute = {p["t"]: p for p in points}
    busy = by_minute[(NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")]
    assert busy["requests"] == 6 and busy["error_rate"] == pytest.approx(1 / 3)
    assert busy["availability"] == pytest.approx(2 / 3) and busy["p95_ms"] >= 104
    empty = by_minute[(NOW - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")]
    assert empty["requests"] == 0 and empty["error_rate"] is None


async def test_baldes_pela_metade_dividem_pelos_segundos_que_cobrem(
    visitor: httpx.AsyncClient, clean_db: str
) -> None:
    # O período começa e termina no meio de um minuto. 30 requisições nos 30 s finais e 15
    # nos 30 s iniciais são 1/s e 0,5/s, e não 0,5/s e 0,25/s (o minuto inteiro).
    since, until = NOW - timedelta(minutes=59, seconds=30), NOW + timedelta(seconds=30)
    rows = [row(f"{i:032x}", "a" * 16, None, NOW + timedelta(seconds=i), 10) for i in range(30)]
    rows += [row(f"{100 + i:032x}", "a" * 16, None, since + timedelta(seconds=i), 10) for i in range(15)]
    await store_rows(clean_db, rows)
    points = (
        await visitor.get(
            "/api/projects/1/services/gateway/metrics",
            params={"since": since.isoformat(), "until": until.isoformat()},
        )
    ).json()["points"]
    assert points[-1]["requests"] == 30 and points[-1]["rps"] == pytest.approx(1.0)
    assert points[0]["requests"] == 15 and points[0]["rps"] == pytest.approx(0.5)


async def test_rotas_do_servico_ordenadas_pelas_mais_usadas(
    visitor: httpx.AsyncClient, clean_db: str
) -> None:
    rows = [row(f"{i:032x}", "a" * 16, None, NOW - timedelta(minutes=5), 80) for i in range(4)]
    rows += [row(f"{50 + i:032x}", "a" * 16, None, NOW - timedelta(minutes=5), 10, name="GET /products",
                 http_route="/products", http_method="GET") for i in range(9)]  # fmt: skip
    await store_rows(clean_db, rows)
    ops = (await visitor.get("/api/projects/1/services/gateway/operations")).json()
    assert [(o["http_method"], o["operation"], o["requests"]) for o in ops] == [
        ("GET", "/products", 9), ("POST", "/checkout", 4),
    ]  # fmt: skip


async def test_traces_que_passaram_pelo_servico(visitor: httpx.AsyncClient, clean_db: str) -> None:
    com_payments, rows_a = checkout(NOW - timedelta(minutes=3))
    so_produtos = "f" * 32
    rows_b = [row(so_produtos, "a" * 16, None, NOW - timedelta(minutes=2), 10, name="GET /products")]
    await store_rows(clean_db, rows_a + rows_b)
    r = await visitor.get("/api/projects/1/traces", params={"through": "payments"})
    assert [t["trace_id"] for t in r.json()["traces"]] == [com_payments]

"""Busca de traces e o waterfall, contra o banco de teste (conftest.py)."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI

from traceflow.api.app import create_app
from traceflow.config import Settings
from traceflow.normalize import SpanRow
from traceflow.storage import SpanStore

pytestmark = pytest.mark.db

NOW = datetime.now(UTC).replace(microsecond=0)


def row(trace: str, span_id: str, parent: str | None, start: datetime, ms: float, **kw: Any) -> SpanRow:
    base: dict[str, Any] = {
        "project_id": 1, "environment": "demo", "service": "gateway", "name": "POST /checkout",
        "kind": "server", "status": "unset", "status_message": None, "http_method": "POST",
        "http_route": "/checkout", "http_status_code": 201, "peer_address": None,
        "attributes": {}, "resource": {}, "events": [],
    }  # fmt: skip
    base.update(kw)
    return SpanRow(
        trace_id=trace, span_id=span_id, parent_span_id=parent, start_time=start, duration_ms=ms, **base
    )


def checkout(start: datetime, ms: float = 120, failed: bool = False) -> tuple[str, list[SpanRow]]:
    trace = secrets.token_hex(16)
    pay_status = "error" if failed else "unset"
    return trace, [
        row(trace, "a" * 16, None, start, ms, http_status_code=502 if failed else 201),
        row(trace, "b" * 16, "a" * 16, start + timedelta(milliseconds=5), ms - 10, service="orders",
            name="POST /orders", http_route="/orders"),
        row(trace, "c" * 16, "b" * 16, start + timedelta(milliseconds=20), ms - 40, service="payments",
            name="POST /charge", http_route="/charge", status=pay_status),
    ]  # fmt: skip


@pytest.fixture
async def app(clean_db: str) -> AsyncIterator[FastAPI]:
    redis = FakeAsyncRedis()
    yield create_app(Settings(database_url=clean_db), redis)
    await redis.aclose()


@pytest.fixture
async def visitor(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        await c.post("/api/auth/demo")
        yield c


async def store_rows(dsn: str, rows: list[SpanRow]) -> None:
    store = await SpanStore.connect(dsn)
    await store.insert(rows)
    await store.close()


async def test_busca_traz_a_raiz_com_os_numeros_do_trace_inteiro(
    visitor: httpx.AsyncClient, clean_db: str
) -> None:
    ok_trace, ok = checkout(NOW - timedelta(minutes=5))
    bad_trace, bad = checkout(NOW - timedelta(minutes=4), ms=900, failed=True)
    await store_rows(clean_db, ok + bad)

    page = (await visitor.get("/api/projects/1/traces")).json()
    assert [t["trace_id"] for t in page["traces"]] == [bad_trace, ok_trace]  # mais recente primeiro
    first = page["traces"][0]
    assert (first["span_count"], first["error_count"], first["service_count"]) == (3, 1, 3)
    assert page["next_cursor"] is None

    async def ids(**params: Any) -> list[str]:
        r = await visitor.get("/api/projects/1/traces", params=params)
        return [t["trace_id"] for t in r.json()["traces"]]

    assert await ids(status="error") == [bad_trace]  # o erro estava num span filho, não na raiz
    assert await ids(status="ok") == [ok_trace]
    assert await ids(min_duration_ms=500) == [bad_trace]
    assert await ids(operation="checkout") == [bad_trace, ok_trace]
    assert await ids(operation="100%_") == []  # % e _ são texto, não curingas
    assert await ids(environment="producao") == []


async def test_spans_um_pouco_fora_da_janela_ainda_contam(visitor: httpx.AsyncClient, clean_db: str) -> None:
    # o limite fixo das subconsultas (a janela com folga) não pode cortar o trace nas bordas
    since, until = NOW - timedelta(minutes=30), NOW - timedelta(minutes=25)
    early, late = secrets.token_hex(16), secrets.token_hex(16)
    early_root, late_root = since + timedelta(seconds=10), until - timedelta(seconds=10)
    payments: dict[str, Any] = {"service": "payments", "name": "POST /charge", "http_route": "/charge"}
    await store_rows(clean_db, [
        row(early, "a" * 16, None, early_root, 120),
        row(early, "c" * 16, "a" * 16, early_root - timedelta(seconds=40), 80, **payments),  # relógio errado
        row(late, "a" * 16, None, late_root, 120),
        row(late, "c" * 16, "a" * 16, late_root + timedelta(minutes=2), 80, **payments),  # depois do fim
    ])  # fmt: skip
    window = {"since": since.isoformat(), "until": until.isoformat()}
    page = (await visitor.get("/api/projects/1/traces", params=window)).json()
    assert {t["trace_id"]: t["span_count"] for t in page["traces"]} == {early: 2, late: 2}
    page = (await visitor.get("/api/projects/1/traces", params=window | {"through": "payments"})).json()
    assert [t["trace_id"] for t in page["traces"]] == [late, early]


async def test_paginacao_por_cursor_nao_repete_nem_pula(visitor: httpx.AsyncClient, clean_db: str) -> None:
    traces = [checkout(NOW - timedelta(minutes=30) + timedelta(seconds=i)) for i in range(7)]
    await store_rows(clean_db, [r for _, rows in traces for r in rows])
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        page = (await visitor.get("/api/projects/1/traces", params=params)).json()
        seen += [t["trace_id"] for t in page["traces"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [t for t, _ in reversed(traces)]
    assert (await visitor.get("/api/projects/1/traces", params={"cursor": "lixo"})).status_code == 422


async def test_trace_completo_vem_em_arvore_com_tempo_proprio(
    visitor: httpx.AsyncClient, clean_db: str
) -> None:
    trace, rows = checkout(NOW - timedelta(minutes=2), ms=200)
    await store_rows(clean_db, rows)
    body = (
        await visitor.get(
            f"/api/projects/1/traces/{trace}", params={"around": rows[0].start_time.isoformat()}
        )
    ).json()
    assert body["duration_ms"] == 200 and body["services"] == ["gateway", "orders", "payments"]
    assert [(s["service"], s["depth"], s["offset_ms"]) for s in body["spans"]] == [
        ("gateway", 0, 0), ("orders", 1, 5), ("payments", 2, 20),
    ]  # fmt: skip
    assert body["spans"][0]["self_time_ms"] == 10  # 200 - 190 do orders
    assert (await visitor.get(f"/api/projects/1/traces/{trace.upper()}")).status_code == 200


async def test_trace_inexistente_ou_de_outro_projeto_e_404(visitor: httpx.AsyncClient, clean_db: str) -> None:
    trace, rows = checkout(NOW - timedelta(minutes=2))
    await store_rows(clean_db, [r.__class__(**{**r.__dict__, "project_id": 99}) for r in rows])
    assert (await visitor.get(f"/api/projects/1/traces/{trace}")).status_code == 404
    assert (await visitor.get("/api/projects/1/traces/nao-e-um-id")).status_code == 404
    assert (
        await visitor.get(f"/api/projects/99/traces/{trace}")
    ).status_code == 404  # o projeto 99 não é visível

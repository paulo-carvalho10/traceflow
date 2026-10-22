"""Regras e incidentes pela API (banco de teste): permissões, validação, evidência e antes / depois."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from test_api import client, signed_up
from test_api_traces import row

from traceflow.api.app import create_app
from traceflow.config import Settings
from traceflow.normalize import SpanRow
from traceflow.storage import SpanStore

pytestmark = pytest.mark.db

NOW = (datetime.now(UTC) - timedelta(minutes=20)).replace(second=0, microsecond=0)
OPENED, RESOLVED = NOW, NOW + timedelta(minutes=3)


@pytest.fixture
async def app(clean_db: str) -> AsyncIterator[FastAPI]:
    redis = FakeAsyncRedis()
    yield create_app(Settings(database_url=clean_db), redis)
    await redis.aclose()


@pytest.fixture
async def visitor(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with client(app) as c:
        await c.post("/api/auth/demo")
        yield c


# ---------- regras ----------


async def test_projeto_da_demonstracao_tem_as_regras_padrao_e_o_visitante_so_le(
    visitor: httpx.AsyncClient,
) -> None:
    rules = (await visitor.get("/api/projects/1/rules")).json()
    assert [(r["metric"], r["threshold"], r["state"]) for r in rules] == [
        ("error_rate", 0.05, "degraded"),
        ("p95_ms", 2.0, "degraded"),
        ("error_rate", 0.25, "failing"),
    ]
    new = {"metric": "p99_ms", "operator": ">=", "threshold": 2000, "state": "failing"}
    assert (await visitor.post("/api/projects/1/rules", json=new)).status_code == 403
    assert (
        await visitor.patch(f"/api/projects/1/rules/{rules[0]['id']}", json={"enabled": False})
    ).status_code == 403


async def test_dono_cria_muda_e_apaga_regras_com_validacao(app: FastAPI) -> None:
    async with signed_up(app) as c:
        project = (await c.post("/api/projects", json={"name": "Loja"})).json()
        base = f"/api/projects/{project['id']}/rules"
        assert len((await c.get(base)).json()) == 3  # todo projeto nasce com as regras padrão

        created = await c.post(
            base,
            json={
                "target": "payments",
                "metric": "p99_ms",
                "operator": ">=",
                "threshold": 2000,
                "state": "failing",
            },
        )
        assert created.status_code == 201
        rule = created.json()
        assert (await c.patch(f"{base}/{rule['id']}", json={"enabled": False})).json()["enabled"] is False

        # validação: relativa só para latência; taxa de erro de 0 a 1 (inclusive ao mudar só o limite)
        relative_errors = {
            "metric": "error_rate",
            "operator": ">=",
            "threshold": 2,
            "relative": True,
            "state": "degraded",
        }
        assert (await c.post(base, json=relative_errors)).status_code == 422
        error_rule = next(r for r in (await c.get(base)).json() if r["metric"] == "error_rate")
        bad = await c.patch(f"{base}/{error_rule['id']}", json={"threshold": 2.0})
        assert bad.status_code == 422 and "de 0 a 1" in bad.json()["detail"]

        assert (await c.delete(f"{base}/{rule['id']}")).status_code == 204
        assert (await c.delete(f"{base}/{rule['id']}")).status_code == 404


# ---------- incidentes ----------


def failed_purchase(i: int, at: datetime) -> list[SpanRow]:
    """gateway 502 ← orders 502 ← payments 500 (a origem), mais um 402 do banco (não é falha)."""
    t = f"{i:032x}"
    return [
        row(t, "a" * 16, None, at, 90, http_status_code=502, status="error"),
        row(
            t,
            "b" * 16,
            "a" * 16,
            at,
            80,
            kind="client",
            peer_address="orders:8000",
            http_status_code=502,
            status="error",
        ),
        row(t, "c" * 16, "b" * 16, at, 70, service="orders", http_status_code=502, status="error"),
        row(
            t,
            "d" * 16,
            "c" * 16,
            at,
            60,
            service="orders",
            kind="client",
            peer_address="payments:8000",
            http_status_code=500,
            status="error",
        ),
        row(t, "e" * 16, "d" * 16, at, 50, service="payments", http_status_code=500, status="error"),
        row(
            t,
            "f" * 16,
            "e" * 16,
            at,
            40,
            service="payments",
            kind="client",
            peer_address="bank:8000",
            http_status_code=402,
            status="error",
        ),
    ]


def ok_purchase(i: int, at: datetime) -> list[SpanRow]:
    return [row(f"{i:032x}", "a" * 16, None, at, 100)]


async def store_incident(dsn: str, incident_id: str) -> None:
    rows: list[SpanRow] = []
    for i in range(10):  # antes: 10 compras boas
        rows += ok_purchase(i, OPENED - timedelta(minutes=2, seconds=i))
    for i in range(10, 16):  # durante: 6 compras, 4 com falha
        at = OPENED + timedelta(minutes=1, seconds=i)
        rows += failed_purchase(i, at) if i < 14 else ok_purchase(i, at)
    for i in range(16, 20):  # depois: 4 compras boas
        rows += ok_purchase(i, RESOLVED + timedelta(minutes=1, seconds=i))
    store = await SpanStore.connect(dsn)
    await store.insert(rows)
    await store.save_incident(
        {
            "id": incident_id,
            "project_id": 1,
            "environment": "demo",
            "status": "resolved",
            "severity": "SEV1",
            "peak_severity": "SEV1",
            "title": "payments falhando",
            "opened_at": OPENED,
            "resolved_at": RESOLVED,
            "causes": [
                {"node": "payments", "state": "failing", "reason": "erro 30%", "own": False, "virtual": False}
            ],
            "affected": [{"node": "orders", "state": "failing", "reason": "erro 28%"}],
            "at_risk": [],
            "endpoints": [
                {
                    "route": "POST /checkout",
                    "service": "gateway",
                    "rps": 6.0,
                    "error_rate": 0.66,
                    "p95_ms": 90.0,
                    "baseline_ms": 100.0,
                }
            ],
        },
        [
            {
                "id": str(uuid.uuid4()),
                "at": OPENED,
                "kind": "opened",
                "message": "Incidente aberto: payments falhando (SEV1)",
                "data": {},
            },
            {
                "id": str(uuid.uuid4()),
                "at": RESOLVED,
                "kind": "resolved",
                "message": "incidente resolvido",
                "data": {},
            },
        ],
    )
    await store.close()


async def test_incidente_com_linha_do_tempo_evidencia_e_antes_depois(
    visitor: httpx.AsyncClient, clean_db: str
) -> None:
    incident_id = str(uuid.uuid4())
    await store_incident(clean_db, incident_id)

    [listed] = (await visitor.get("/api/projects/1/incidents", params={"status": "resolved"})).json()
    assert listed["id"] == incident_id and listed["causes"] == ["payments"]
    assert (await visitor.get("/api/projects/1/incidents", params={"status": "open"})).json() == []

    detail = (await visitor.get(f"/api/projects/1/incidents/{incident_id}")).json()
    assert [e["kind"] for e in detail["events"]] == ["opened", "resolved"]
    # onde os erros nasceram: o payments (o 500 dele não tem filho com falha; o 402 do banco não conta)
    assert detail["error_origins"][0] == {"service": "payments", "origins": 4, "share": 1.0}
    [checkout] = detail["comparison"]
    assert checkout["route"] == "POST /checkout"
    assert checkout["before"]["requests"] == 10 and checkout["before"]["error_rate"] == 0
    assert checkout["worst"]["error_rate"] == pytest.approx(4 / 6)
    assert checkout["after"]["requests"] == 4 and checkout["after"]["error_rate"] == 0
    assert checkout["after_complete"] is True  # resolvido há mais de 5 min: o resumo fica guardado


async def test_incidente_de_outro_projeto_ou_id_invalido_e_404(
    visitor: httpx.AsyncClient, app: FastAPI
) -> None:
    assert (await visitor.get(f"/api/projects/1/incidents/{uuid.uuid4()}")).status_code == 404
    assert (await visitor.get("/api/projects/1/incidents/nao-e-um-id")).status_code == 404
    async with signed_up(app, "outra@exemplo.com") as other:
        assert (await other.get("/api/projects/999/incidents")).status_code == 404

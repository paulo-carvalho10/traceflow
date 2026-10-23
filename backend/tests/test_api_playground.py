"""O Incident Playground pela API (banco de teste para o login, Redis falso para o caos)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI

from traceflow.api.app import create_app
from traceflow.api.playground import ACTIVE_KEY, TRAFFIC_KEY, chaos_key
from traceflow.config import Settings

pytestmark = pytest.mark.db


@pytest.fixture
async def chaos() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    yield client
    await client.aclose()


async def visitor_of(app: FastAPI) -> httpx.AsyncClient:
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    await c.post("/api/auth/demo")
    return c


@pytest.fixture
async def visitor(clean_db: str, chaos: FakeAsyncRedis) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url=clean_db), FakeAsyncRedis(), playground_redis=chaos)
    c = await visitor_of(app)
    yield c
    await c.aclose()


async def test_estado_inicial_tem_os_4_cenarios_e_o_trafego_padrao(visitor: httpx.AsyncClient) -> None:
    state = (await visitor.get("/api/playground")).json()
    assert [s["id"] for s in state["scenarios"]] == [
        "pagamentos-instaveis", "banco-lento", "email-fora", "estoque-fora",
    ]  # fmt: skip
    assert state["active"] is None and state["last"] is None
    assert state["traffic"] == {
        "rps": 20.0, "checkout_ratio": 0.3, "custom": False, "expires_at": None,
        "default_rps": 20.0, "default_checkout_ratio": 0.3,
    }  # fmt: skip


async def test_uma_falha_por_vez_e_ela_expira_sozinha(
    visitor: httpx.AsyncClient, chaos: FakeAsyncRedis
) -> None:
    started = await visitor.post("/api/playground/scenarios/pagamentos-instaveis", json={"duration_s": 120})
    assert started.status_code == 200
    active = started.json()["active"]
    assert active["title"] == "Pagamentos instáveis" and active["faults"]["payments"]["error_rate"] == 0.3
    # o que a loja lê: o hash do caos, com prazo
    assert await chaos.hget(chaos_key("payments"), "error_rate") == b"0.3"
    assert 0 < await chaos.ttl(chaos_key("payments")) <= 120
    assert 0 < await chaos.ttl(ACTIVE_KEY) <= 120
    # um segundo visitante (ou o mesmo) não começa outra
    other = await visitor.post("/api/playground/scenarios/banco-lento")
    assert other.status_code == 409 and "em andamento" in other.json()["detail"]
    manual = await visitor.post("/api/playground/faults", json={"service": "bank", "kind": "down"})
    assert manual.status_code == 409

    await chaos.delete(ACTIVE_KEY)  # como se o prazo acabasse
    state = (await visitor.get("/api/playground")).json()
    assert state["active"] is None and state["last"]["ended_by"] == "expired"


async def test_encerrar_conserta_a_loja_na_hora(visitor: httpx.AsyncClient, chaos: FakeAsyncRedis) -> None:
    await visitor.post("/api/playground/scenarios/estoque-fora")
    assert await chaos.hget(chaos_key("inventory"), "down") == b"1"
    state = (await visitor.delete("/api/playground/faults")).json()
    assert state["active"] is None and state["last"]["ended_by"] == "stopped"
    assert await chaos.exists(chaos_key("inventory")) == 0
    # e dá para começar outra logo em seguida
    assert (await visitor.post("/api/playground/scenarios/banco-lento")).status_code == 200


async def test_falha_manual_e_validada(visitor: httpx.AsyncClient, chaos: FakeAsyncRedis) -> None:
    gateway = await visitor.post("/api/playground/faults", json={"service": "gateway", "kind": "down"})
    assert gateway.status_code == 422  # a porta de entrada fica de fora
    too_slow = await visitor.post(
        "/api/playground/faults", json={"service": "bank", "kind": "latency", "latency_ms": 60_000}
    )
    assert too_slow.status_code == 422
    ok = await visitor.post(
        "/api/playground/faults",
        json={"service": "bank", "kind": "latency", "latency_ms": 800, "duration_s": 60},
    )
    assert ok.json()["active"]["title"] == "bank: +800 ms"
    assert ok.json()["active"]["expect_cause"] == ["bank:8000"]  # externo: aparece pelo endereço
    assert await chaos.hget(chaos_key("bank"), "latency_ms") == b"800"


async def test_trafego_muda_e_volta_sozinho_ao_padrao(
    visitor: httpx.AsyncClient, chaos: FakeAsyncRedis
) -> None:
    state = (await visitor.put("/api/playground/traffic", json={"rps": 40, "checkout_ratio": 0.6})).json()
    assert state["traffic"]["custom"] is True and state["traffic"]["rps"] == 40
    assert await chaos.hget(TRAFFIC_KEY, "rps") == b"40.0"
    assert 0 < await chaos.ttl(TRAFFIC_KEY) <= 600  # volta sozinho em 10 min
    assert (
        await visitor.put("/api/playground/traffic", json={"rps": 500, "checkout_ratio": 0.6})
    ).status_code == 422
    state = (await visitor.delete("/api/playground/traffic")).json()
    assert state["traffic"]["custom"] is False and state["traffic"]["rps"] == 20


async def test_limite_de_falhas_por_visitante(clean_db: str, chaos: FakeAsyncRedis) -> None:
    app = create_app(
        Settings(database_url=clean_db, playground_starts_per_window=2),
        FakeAsyncRedis(),
        playground_redis=chaos,
    )
    c = await visitor_of(app)
    for _ in range(2):
        assert (await c.post("/api/playground/scenarios/email-fora")).status_code == 200
        await c.delete("/api/playground/faults")
    third = await c.post("/api/playground/scenarios/email-fora")
    assert third.status_code == 429
    await c.aclose()


async def test_sem_login_401_e_sem_a_loja_503(clean_db: str) -> None:
    app = create_app(Settings(database_url=clean_db), FakeAsyncRedis())  # sem o Redis do caos
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        assert (await c.get("/api/playground")).status_code == 401
        await c.post("/api/auth/demo")
        assert (await c.get("/api/playground")).status_code == 503

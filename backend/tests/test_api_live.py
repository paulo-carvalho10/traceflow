"""O canal ao vivo: o LiveHub (unidade) e o WebSocket de ponta a ponta (com o banco de teste)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator

import asyncpg
import pytest
from conftest import CLEAN
from fakeredis import FakeAsyncRedis
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from traceflow.api.app import create_app
from traceflow.api.live import LiveHub, Subscriber
from traceflow.config import Settings
from traceflow.streams import LIVE_CHANNEL, LIVE_TICK, snapshot_key

ORIGIN = {"origin": "http://localhost:3000"}


def snapshot(project: int = 1, environment: str = "demo", rps: float = 5.0) -> str:
    return json.dumps(
        {"project_id": project, "environment": environment, "services": [], "entry": {"rps": rps}}
    )


# ---------- unidade ----------


def test_hub_entrega_so_a_quem_olha_aquele_projeto_e_ambiente() -> None:
    hub = LiveHub(None)  # type: ignore[arg-type]
    demo, prod = Subscriber(), Subscriber()
    hub.subscribe(demo, (1, "demo"))
    hub.subscribe(prod, (1, "prod"))
    assert hub.dispatch(snapshot(1, "demo")) == 1
    assert demo.queue.qsize() == 1 and prod.queue.qsize() == 0
    hub.subscribe(demo, (1, "prod"))  # trocou de ambiente: sai do canal anterior
    assert hub.dispatch(snapshot(1, "demo")) == 0
    assert hub.dispatch("isto não é json") == 0
    hub.unsubscribe(prod)
    hub.unsubscribe(demo)
    assert hub.channels == {}


def test_tique_avisa_sem_trafego_so_quem_nao_recebeu_retrato() -> None:
    hub = LiveHub(None)  # type: ignore[arg-type]
    demo, prod = Subscriber(), Subscriber()
    hub.subscribe(demo, (1, "demo"))
    hub.subscribe(prod, (1, "prod"))
    hub.dispatch(snapshot(1, "demo"))
    assert hub.dispatch(LIVE_TICK) == 1  # só o prod: o demo acabou de receber o retrato do segundo
    assert json.loads(demo.queue.get_nowait())["type"] == "snapshot" and demo.queue.empty()
    assert json.loads(prod.queue.get_nowait()) == {"type": "idle"}
    assert hub.dispatch(LIVE_TICK) == 2  # um segundo inteiro sem retrato: agora os dois


def test_aba_lenta_fica_com_o_retrato_mais_novo() -> None:
    sub = Subscriber()
    for rps in range(10):
        sub.offer(snapshot(rps=rps))
    assert sub.queue.qsize() == 2 and sub.dropped == 8
    sub.queue.get_nowait()
    assert json.loads(sub.queue.get_nowait())["entry"]["rps"] == 9


# ---------- WebSocket de ponta a ponta ----------


@pytest.fixture
def client(database_dsn: str) -> Iterator[tuple[TestClient, FakeAsyncRedis]]:
    async def clean() -> None:
        connection = await asyncpg.connect(database_dsn)
        await connection.execute(CLEAN)
        await connection.close()

    asyncio.run(clean())
    redis = FakeAsyncRedis()
    app = create_app(Settings(database_url=database_dsn), redis)
    with TestClient(app) as test_client:  # sobe a API, com o LiveHub escutando o canal
        yield test_client, redis


def wait_hub_listening(c: TestClient, redis: FakeAsyncRedis) -> None:
    for _ in range(50):
        [(_, listeners)] = c.portal.call(redis.pubsub_numsub, LIVE_CHANNEL)  # type: ignore[union-attr]
        if listeners:
            return
        time.sleep(0.05)
    raise AssertionError("o LiveHub não assinou o canal")


@pytest.mark.db
def test_websocket_entrega_o_retrato_atual_e_os_seguintes(client: tuple[TestClient, FakeAsyncRedis]) -> None:
    c, redis = client
    c.post("/api/auth/demo")
    ticket = c.post("/api/live/ticket").json()["ticket"]
    c.portal.call(redis.set, snapshot_key(1, "demo"), snapshot(rps=3))  # type: ignore[union-attr]
    wait_hub_listening(c, redis)

    with c.websocket_connect(f"/api/live?ticket={ticket}", headers=ORIGIN) as ws:
        ws.send_json({"type": "subscribe", "project_id": 1, "environment": "demo"})
        assert ws.receive_json() == {"type": "subscribed", "project_id": 1, "environment": "demo"}
        first = ws.receive_json()
        assert first["type"] == "snapshot" and first["data"]["entry"]["rps"] == 3  # o atual, na hora
        c.portal.call(redis.publish, LIVE_CHANNEL, snapshot(rps=7))  # type: ignore[union-attr]
        assert ws.receive_json()["data"]["entry"]["rps"] == 7  # e o seguinte, quando o processador publica
        ws.send_json({"type": "subscribe", "project_id": 1, "environment": "prod"})  # nada chega daqui
        assert ws.receive_json()["type"] == "subscribed"
        c.portal.call(redis.publish, LIVE_CHANNEL, LIVE_TICK)  # type: ignore[union-attr]
        assert ws.receive_json() == {"type": "idle"}  # o processamento está no ar: é falta de tráfego
        ws.send_json({"type": "subscribe", "project_id": 99, "environment": "demo"})
        assert ws.receive_json() == {"type": "error", "detail": "projeto não encontrado"}


@pytest.mark.db
def test_ticket_vale_uma_vez_e_origem_estranha_e_recusada(client: tuple[TestClient, FakeAsyncRedis]) -> None:
    c, _ = client
    c.post("/api/auth/demo")
    ticket = c.post("/api/live/ticket").json()["ticket"]

    with pytest.raises(
        WebSocketDisconnect
    ):  # outro site tentando abrir o canal com a sessão de quem o visita
        with c.websocket_connect(
            f"/api/live?ticket={ticket}", headers={"origin": "https://site-malicioso.com"}
        ):
            pass
    with c.websocket_connect(f"/api/live?ticket={ticket}", headers=ORIGIN):
        pass  # o ticket ainda valia: a origem foi recusada antes de ele ser consumido
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/live?ticket={ticket}", headers=ORIGIN):  # segunda vez: já foi usado
            pass
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/api/live", headers=ORIGIN):  # sem ticket
            pass


@pytest.mark.db
def test_ticket_exige_login(client: tuple[TestClient, FakeAsyncRedis]) -> None:
    c, _ = client
    assert c.post("/api/live/ticket").status_code == 401

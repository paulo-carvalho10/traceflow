"""O estado ao vivo, por WebSocket.

    POST /api/live/ticket     pede um ticket de uso único (precisa estar logado)
    WS   /api/live?ticket=…   abre o canal; o cliente diz o que quer ver:
                              {"type": "subscribe", "project_id": 1, "environment": "demo"}
                              e recebe o retrato atual, e depois um por segundo

Por que um ticket, e não o cookie? Em produção o front fica na Vercel e a API em outro
endereço (D24); a Vercel não repassa WebSocket, e o navegador conecta direto na API. O
ticket funciona em qualquer arranjo de domínios: é pedido por REST (com o cookie), vale
30 s e é apagado no primeiro uso.

A origem da conexão também é conferida: sem isso, uma página de outro site poderia abrir um
WebSocket com a sessão de quem a visita (Cross-Site WebSocket Hijacking).

Uma assinatura do Redis por processo da API, não uma por aba: o LiveHub recebe cada retrato
uma vez e entrega a quem está olhando aquele projeto e ambiente.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from collections import defaultdict
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from traceflow.api.deps import RedisDep, UserDep, can_read
from traceflow.models import Project, User
from traceflow.streams import LIVE_CHANNEL, snapshot_key

log = logging.getLogger("traceflow.api.live")
router = APIRouter(prefix="/api/live", tags=["ao vivo"])

TICKET_TTL_S = 30
POLICY_VIOLATION = 1008  # código de fechamento do WebSocket: "você não pode"


def ticket_key(ticket: str) -> str:
    return f"traceflow:ticket:{ticket}"


class Ticket(BaseModel):
    ticket: str
    expires_in: int


@router.post("/ticket")
async def create_ticket(user: UserDep, redis_client: RedisDep) -> Ticket:
    ticket = secrets.token_urlsafe(24)
    await redis_client.set(ticket_key(ticket), user.id, ex=TICKET_TTL_S)
    return Ticket(ticket=ticket, expires_in=TICKET_TTL_S)


Channel = tuple[int, str]  # (projeto, ambiente)


class Subscriber:
    """Uma aba. A fila guarda no máximo 2 retratos: se a aba estiver lenta, o mais velho sai.

    Para dado ao vivo, o retrato mais novo vale mais que todos os anteriores. Uma fila sem
    limite faria uma aba lenta acumular retratos velhos (e memória) para sempre.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
        self.channel: Channel | None = None
        self.dropped = 0

    def offer(self, payload: str) -> None:
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(payload)


class LiveHub:
    def __init__(self, client: redis.Redis) -> None:
        self.redis = client
        self.channels: dict[Channel, set[Subscriber]] = defaultdict(set)

    def subscribe(self, subscriber: Subscriber, channel: Channel) -> None:
        self.unsubscribe(subscriber)
        subscriber.channel = channel
        self.channels[channel].add(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        if subscriber.channel is not None:
            self.channels[subscriber.channel].discard(subscriber)
            if not self.channels[subscriber.channel]:
                del self.channels[subscriber.channel]
            subscriber.channel = None

    def dispatch(self, payload: str) -> int:
        """Entrega um retrato a quem está olhando aquele projeto e ambiente. Devolve quantos receberam."""
        try:
            data = json.loads(payload)
            channel = (int(data["project_id"]), str(data["environment"]))
        except (ValueError, KeyError, TypeError):
            return 0
        subscribers = self.channels.get(channel, ())
        for subscriber in subscribers:
            subscriber.offer(payload)
        return len(subscribers)

    async def run(self) -> None:
        """Escuta o canal do Redis para sempre, reconectando se ele cair."""
        delay = 0.5
        while True:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe(LIVE_CHANNEL)
                delay = 0.5
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        data = message["data"]
                        self.dispatch(data.decode() if isinstance(data, bytes) else data)
            except redis.RedisError as exc:
                log.warning("perdi o canal ao vivo (%s); reconectando em %.1fs", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10.0)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()


@router.websocket("")
async def live(ws: WebSocket, ticket: str = "") -> None:
    app = ws.app
    settings = app.state.settings
    redis_client: redis.Redis = app.state.redis
    hub: LiveHub = app.state.live_hub

    origin = ws.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        await ws.close(code=POLICY_VIOLATION, reason="origem não permitida")
        return
    # GETDEL: lê e apaga num comando só. Um ticket nunca serve duas vezes, nem em corrida.
    user_id = await redis_client.getdel(ticket_key(ticket)) if ticket else None
    if user_id is None:
        await ws.close(code=POLICY_VIOLATION, reason="ticket inválido ou vencido")
        return
    async with app.state.sessionmaker() as db:
        user = await db.get(User, int(user_id))
    if user is None:
        await ws.close(code=POLICY_VIOLATION, reason="conta não encontrada")
        return

    await ws.accept()
    subscriber = Subscriber()
    # Duas tarefas escrevem neste socket (a que responde ao cliente e a que repassa os
    # retratos): a trava garante uma mensagem inteira de cada vez, sem misturar quadros.
    lock = asyncio.Lock()

    async def send(payload: str) -> None:
        async with lock:
            await ws.send_text(payload)

    sender = asyncio.create_task(_send_forever(subscriber, send))
    try:
        while True:
            try:
                message = json.loads(await ws.receive_text())
            except ValueError:
                await send(json.dumps({"type": "error", "detail": "mensagem não é JSON"}))
                continue
            if message.get("type") != "subscribe":
                await send(json.dumps({"type": "error", "detail": "tipo de mensagem desconhecido"}))
                continue
            channel = await _authorized_channel(app, user, message)
            if channel is None:
                await send(json.dumps({"type": "error", "detail": "projeto não encontrado"}))
                continue
            hub.subscribe(subscriber, channel)
            await send(
                json.dumps({"type": "subscribed", "project_id": channel[0], "environment": channel[1]})
            )
            current = await redis_client.get(snapshot_key(*channel))
            if current is not None:
                subscriber.offer(current.decode() if isinstance(current, bytes) else current)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(subscriber)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender


async def _authorized_channel(app: object, user: User, message: dict[str, object]) -> Channel | None:
    try:
        project_id = int(message["project_id"])  # type: ignore[call-overload]
        environment = str(message["environment"])
    except (KeyError, TypeError, ValueError):
        return None
    async with app.state.sessionmaker() as db:  # type: ignore[attr-defined]
        project = await db.get(Project, project_id)
    if project is None or not can_read(project, user):
        return None
    return project_id, environment


async def _send_forever(subscriber: Subscriber, send: Callable[[str], Awaitable[None]]) -> None:
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            payload = await subscriber.queue.get()
            # o retrato já é JSON: vai embrulhado sem decodificar e codificar de novo
            await send(f'{{"type":"snapshot","data":{payload}}}')

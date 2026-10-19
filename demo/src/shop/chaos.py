"""Falhas injetadas de propósito: o laboratório da demonstração.

A configuração de cada serviço fica no Redis, no hash `demo:chaos:{serviço}`:

    latency_ms   atraso somado a cada requisição, em milissegundos
    error_rate   fração das requisições que respondem 500, de 0 a 1
    down         "1" deixa o serviço fora do ar

Cada serviço relê o hash a cada segundo. Sem Redis, ou sem o hash, não há caos.

As falhas ficam em duas camadas, e a posição de cada uma é o que importa:

    OutageSwitch        por fora da instrumentação: "fora do ar" responde 503 sem gerar span,
      OpenTelemetry     como o balanceador na frente de um serviço caído
        ChaosMiddleware por dentro: o atraso e o erro aparecem no span, como uma falha real
          rotas
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import cast

import redis.asyncio as redis
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)


def chaos_key(service: str) -> str:
    return f"demo:chaos:{service}"


@dataclass(frozen=True)
class ChaosConfig:
    latency_ms: float = 0.0
    error_rate: float = 0.0
    down: bool = False

    @classmethod
    def parse(cls, raw: Mapping[str, str]) -> ChaosConfig:
        """Lê o hash do Redis. Um campo inválido é ignorado, nunca derruba o serviço."""

        def number(field: str, low: float, high: float) -> float:
            try:
                return min(high, max(low, float(raw.get(field, 0))))
            except ValueError:
                return 0.0

        return cls(
            latency_ms=number("latency_ms", 0, 60_000),
            error_rate=number("error_rate", 0, 1),
            down=raw.get("down", "0").strip().lower() in {"1", "true", "sim"},
        )

    @property
    def active(self) -> bool:
        return self != ChaosConfig()


class Chaos:
    """A configuração de caos atual de um serviço, atualizada em segundo plano."""

    def __init__(
        self,
        service: str,
        redis_url: str | None,
        *,
        interval: float = 1.0,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.service = service
        self.redis_url = redis_url
        self.interval = interval
        self.rng = rng
        self.config = ChaosConfig()

    def should_fail(self) -> bool:
        return self.config.error_rate > 0 and self.rng() < self.config.error_rate

    @asynccontextmanager
    async def polling(self) -> AsyncIterator[None]:
        if not self.redis_url:
            yield
            return
        client = redis.from_url(self.redis_url, decode_responses=True)
        task = asyncio.create_task(self._poll(client))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await client.aclose()

    async def _poll(self, client: redis.Redis) -> None:
        while True:
            try:
                # decode_responses=True: o Redis devolve str, não bytes
                raw = cast(dict[str, str], await client.hgetall(chaos_key(self.service)))
                config = ChaosConfig.parse(raw)
            except redis.RedisError as exc:
                # Sem como ler a configuração, o serviço volta ao normal: caos preso ligado é pior.
                log.warning("caos: não consegui ler o Redis (%s); seguindo sem falhas", exc)
                config = ChaosConfig()
            if config != self.config:
                log.warning("caos em %s: %s", self.service, config)
                self.config = config
            await asyncio.sleep(self.interval)


async def send_json(send: Send, status: int, body: dict[str, str]) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class ChaosMiddleware:
    """Atraso e erro injetados por dentro da instrumentação: aparecem no span do serviço."""

    def __init__(self, app: ASGIApp, chaos: Chaos) -> None:
        self.app = app
        self.chaos = chaos

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        config = self.chaos.config
        if config.latency_ms:
            await asyncio.sleep(config.latency_ms / 1000)
        if self.chaos.should_fail():
            await send_json(send, 500, {"detail": f"falha injetada pelo caos em {self.chaos.service}"})
            return
        await self.app(scope, receive, send)


class OutageSwitch:
    """ "Fora do ar" por fora da instrumentação: o serviço some dos traces, como um serviço caído."""

    def __init__(self, app: ASGIApp, chaos: Chaos) -> None:
        self.app = app
        self.chaos = chaos

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.chaos.config.down:
            await send_json(send, 503, {"detail": f"{self.chaos.service} fora do ar (caos)"})
            return
        await self.app(scope, receive, send)

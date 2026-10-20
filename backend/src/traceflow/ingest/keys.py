"""Quem está mandando estes spans? A ingestão descobre pela chave, com cache.

Cada lote traz `Authorization: Bearer tf_<prefixo>_<segredo>`. O prefixo acha a chave no
banco; o SHA-256 do segredo é comparado com o hash guardado. O resultado fica em memória
por 60 s: mil lotes por segundo com a mesma chave viram uma consulta ao banco por minuto.

Três respostas possíveis, e a diferença entre elas importa para o exportador:
    projeto  -> aceita
    None     -> 401: chave ausente, errada ou revogada. Não adianta tentar de novo.
    KeyUnavailable -> 503: o banco está fora e a chave não está no cache. Tente daqui a pouco.
Responder 401 com o banco fora faria o exportador jogar fora dados de uma chave válida.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import asyncpg

from traceflow.security import parse_key, secret_matches
from traceflow.storage import ANY_DB_ERROR

log = logging.getLogger("traceflow.ingest.keys")

MAX_CACHED_KEYS = 10_000  # prefixos inventados por alguém não podem encher a memória


class KeyUnavailable(Exception):
    """Não deu para conferir a chave agora (o banco não respondeu e ela não está no cache)."""


@dataclass(frozen=True)
class KeyRecord:
    project_id: int
    secret_hash: str
    revoked: bool


class KeyLookup(Protocol):
    async def find(self, prefix: str) -> KeyRecord | None: ...
    async def touch(self, prefix: str) -> None: ...


@dataclass
class _Cached:
    record: KeyRecord | None
    expires_at: float


class KeyVerifier:
    def __init__(
        self,
        lookup: KeyLookup,
        *,
        ttl_s: float,
        negative_ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.lookup = lookup
        self.ttl_s = ttl_s
        self.negative_ttl_s = negative_ttl_s
        self.clock = clock
        self._cache: dict[str, _Cached] = {}
        # Consultas em andamento, por prefixo: quem chega enquanto uma está no ar espera por ela
        self._inflight: dict[str, asyncio.Task[KeyRecord | None]] = {}

    async def project_for(self, authorization: str | None) -> int | None:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer":
            return None
        parsed = parse_key(token)
        if parsed is None:
            return None
        prefix, secret = parsed
        record = await self._record(prefix)
        if record is None or record.revoked or not secret_matches(secret, record.secret_hash):
            return None
        return record.project_id

    async def _record(self, prefix: str) -> KeyRecord | None:
        cached = self._cache.get(prefix)
        if cached is not None and cached.expires_at > self.clock():
            return cached.record
        # Uma consulta só por chave, por vez ("single-flight"). Quando o cache vence, vários lotes
        # chegam juntos e todos o veem vencido; sem isto, todos iriam ao banco ao mesmo tempo
        # (o "estouro de cache"). Com isto, um vai, e os outros esperam o mesmo resultado.
        task = self._inflight.get(prefix)
        if task is None:
            task = asyncio.create_task(self._refresh(prefix, cached))
            self._inflight[prefix] = task
            task.add_done_callback(lambda _: self._inflight.pop(prefix, None))
        return await asyncio.shield(task)  # quem desistir de esperar não cancela a consulta dos outros

    async def _refresh(self, prefix: str, cached: _Cached | None) -> KeyRecord | None:
        now = self.clock()
        try:
            record = await self.lookup.find(prefix)
        except ANY_DB_ERROR as exc:
            if cached is not None:
                # Banco fora, mas a chave já era conhecida: segue valendo o que se sabia.
                # Melhor aceitar spans de uma chave que pode ter sido revogada há instantes
                # do que recusar os de todas as chaves válidas enquanto o banco não volta.
                # E só tenta o banco de novo daqui a pouco: sem isso, cada lote tentaria uma
                # conexão (e escreveria um aviso) durante toda a queda.
                cached.expires_at = now + self.negative_ttl_s
                log.warning("banco indisponível ao conferir a chave %s (%s); usando o cache", prefix, exc)
                return cached.record
            raise KeyUnavailable(str(exc)) from exc
        self._remember(prefix, record, now)
        if record is not None and not record.revoked:
            try:
                await self.lookup.touch(prefix)  # "usada pela última vez", no máximo uma vez por minuto
            except ANY_DB_ERROR:
                pass
        return record

    def _remember(self, prefix: str, record: KeyRecord | None, now: float) -> None:
        if len(self._cache) >= MAX_CACHED_KEYS:
            self._cache = {p: c for p, c in self._cache.items() if c.expires_at > now}
            if len(self._cache) >= MAX_CACHED_KEYS:
                self._cache.clear()
        ttl = self.ttl_s if record is not None else self.negative_ttl_s
        self._cache[prefix] = _Cached(record, now + ttl)


class PostgresKeyLookup:
    """Consulta as chaves direto no PostgreSQL (asyncpg): a ingestão não carrega o ORM."""

    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresKeyLookup:
        # min_size=0: a ingestão sobe mesmo com o banco fora; as conexões nascem quando precisar
        return cls(await asyncpg.create_pool(dsn, min_size=0, max_size=2))

    async def close(self) -> None:
        await self.pool.close()

    async def find(self, prefix: str) -> KeyRecord | None:
        row = await self.pool.fetchrow(
            "SELECT project_id, secret_hash, revoked_at IS NOT NULL AS revoked "
            "FROM api_keys WHERE prefix = $1",
            prefix,
        )
        if row is None:
            return None
        return KeyRecord(project_id=row["project_id"], secret_hash=row["secret_hash"], revoked=row["revoked"])

    async def touch(self, prefix: str) -> None:
        await self.pool.execute("UPDATE api_keys SET last_used_at = now() WHERE prefix = $1", prefix)

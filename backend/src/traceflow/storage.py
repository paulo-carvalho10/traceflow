"""Gravação de spans no TimescaleDB, em lote.

O caminho mais rápido para pôr milhares de linhas no PostgreSQL é o COPY, mas o COPY não
sabe "ignorar se já existe". Então cada lote vai por COPY para uma tabela temporária e,
de lá, para a tabela de verdade com INSERT ... ON CONFLICT DO NOTHING, numa transação só.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import asyncpg
from asyncpg.pool import PoolConnectionProxy

from traceflow.normalize import COLUMNS, SpanRow

log = logging.getLogger("traceflow.storage")

# Falhas passageiras: o banco caiu, está desligando ou reiniciando, ou está sem conexões livres.
# Quem chama deve esperar e tentar de novo. Qualquer outro erro do banco é problema no dado.
TRANSIENT_DB_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    TimeoutError,
    asyncpg.InterfaceError,  # inclui ConnectionDoesNotExistError
    asyncpg.PostgresConnectionError,  # classe 08: conexão
    asyncpg.OperatorInterventionError,  # classe 57: desligando (AdminShutdown), ainda subindo
    asyncpg.InsufficientResourcesError,  # classe 53: sem conexões, sem disco
)
# Qualquer falha do banco, passageira ou não: para quem só quer seguir em frente se o banco falhar.
ANY_DB_ERROR: tuple[type[BaseException], ...] = (*TRANSIENT_DB_ERRORS, asyncpg.PostgresError)

CREATE_STAGING = """
CREATE TEMP TABLE IF NOT EXISTS spans_in (LIKE spans INCLUDING DEFAULTS) ON COMMIT DELETE ROWS
"""
# O catálogo de serviços: um registro por (projeto, ambiente, serviço), com a última vez visto.
UPSERT_SERVICES = """
INSERT INTO services (project_id, environment, name, first_seen, last_seen)
SELECT p, e, n, t, t FROM unnest($1::int[], $2::text[], $3::text[], $4::timestamptz[]) AS x(p, e, n, t)
ON CONFLICT (project_id, environment, name)
DO UPDATE SET last_seen = GREATEST(services.last_seen, excluded.last_seen)
"""
MOVE_FROM_STAGING = f"""
INSERT INTO spans ({", ".join(COLUMNS)})
SELECT {", ".join(COLUMNS)} FROM spans_in
ON CONFLICT DO NOTHING
"""


JSONB_VERSION = b"\x01"


def _encode_jsonb(value: Any) -> bytes:
    return JSONB_VERSION + json.dumps(value).encode()


def _decode_jsonb(data: bytes) -> Any:
    return json.loads(data[1:])


async def _init_connection(connection: asyncpg.Connection[Any]) -> None:
    # Os dicionários e listas do Python viram JSONB (e voltam) sem conversão manual.
    # Em formato BINÁRIO, porque é o formato que o COPY usa: o JSONB binário é um byte de
    # versão (1) seguido do texto do JSON. Um codec só de texto quebra o COPY.
    await connection.set_type_codec(
        "jsonb", encoder=_encode_jsonb, decoder=_decode_jsonb, schema="pg_catalog", format="binary"
    )
    await connection.set_type_codec(
        "json",
        encoder=lambda v: json.dumps(v).encode(),
        decoder=json.loads,
        schema="pg_catalog",
        format="binary",
    )


class SpanStore:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> SpanStore:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, init=_init_connection)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def insert(self, rows: Sequence[SpanRow]) -> int:
        """Grava os spans e devolve quantos eram novos. Repetidos são ignorados (idempotente)."""
        if not rows:
            return 0
        connection = await self.pool.acquire()
        try:
            async with connection.transaction():
                await connection.execute(CREATE_STAGING)
                await connection.copy_records_to_table(
                    "spans_in", records=[row.as_record() for row in rows], columns=list(COLUMNS)
                )
                status = await connection.execute(MOVE_FROM_STAGING)  # "INSERT 0 <n>"
        except BaseException as exc:
            lost = connection.is_closed()
            await self._give_back(connection, exc)
            # Quando o servidor derruba uma conexão parada, o asyncpg não avisa "conexão caiu":
            # o próximo comando falha com InternalClientError, o mesmo tipo de erro de um bug.
            # O que separa os dois casos é a conexão ter fechado. Se fechou, foi queda, e quem
            # chamou deve esperar e tentar de novo. Se não fechou, é bug, e o erro sobe como está.
            if lost and isinstance(exc, asyncpg.InternalClientError):
                raise asyncpg.ConnectionDoesNotExistError("a conexão com o banco caiu") from exc
            raise
        await self.pool.release(connection)
        return int(status.rsplit(" ", 1)[-1])

    async def upsert_services(self, seen: Sequence[tuple[int, str, str, datetime]]) -> None:
        """Registra no catálogo os serviços vistos: (projeto, ambiente, serviço, quando)."""
        if not seen:
            return
        projects, environments, names, times = zip(*seen, strict=True)
        await self.pool.execute(UPSERT_SERVICES, list(projects), list(environments), list(names), list(times))

    async def _give_back(self, connection: PoolConnectionProxy[Any], error: BaseException) -> None:
        """Devolve ao pool uma conexão que acabou de falhar, sem nunca esconder o erro original.

        Só um erro de dado (o servidor recusou a linha) deixa a conexão confiável: a transação
        foi desfeita e ela pode ser reaproveitada. Em qualquer outro caso (queda, desligamento
        do servidor, cancelamento) ela é descartada, e o pool abre outra quando precisar.
        Devolvida "suja", o pool tentaria limpá-la, a limpeza falharia, e esse erro novo
        substituiria o original, que era o que dizia "tente de novo".
        """
        data_error = isinstance(error, asyncpg.PostgresError) and not isinstance(error, TRANSIENT_DB_ERRORS)
        if not data_error or connection.is_closed():
            connection.terminate()
        try:
            await self.pool.release(connection)
        except Exception as release_error:  # o pool já descarta a conexão nesse caso
            log.debug("conexão descartada ao devolver ao pool: %s", release_error)

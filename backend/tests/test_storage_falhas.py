"""O que o SpanStore faz com a conexão quando a gravação falha (sem banco: pool e conexão de mentira).

Reproduz a queda real vista na Etapa 3: o servidor desliga no meio da gravação
(AdminShutdownError) e a limpeza da conexão, ao devolvê-la ao pool, falha com
InternalClientError. O erro que sobe tem de ser o original, que é passageiro.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import pytest
from helpers import export_request

from traceflow.normalize import SpanRow, normalize
from traceflow.storage import TRANSIENT_DB_ERRORS, SpanStore


class FakeConnection:
    def __init__(self, error: BaseException, closed: bool = False) -> None:
        self.error = error
        self.closed = closed
        self.terminated = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def execute(self, query: str) -> str:
        raise self.error

    def is_closed(self) -> bool:
        return self.closed or self.terminated

    def terminate(self) -> None:
        self.terminated = True


class FakePool:
    """Como o pool do asyncpg: devolver uma conexão aberta passa por uma limpeza (reset)."""

    def __init__(self, connection: FakeConnection, reset_fails: bool) -> None:
        self.connection = connection
        self.reset_fails = reset_fails
        self.released = 0

    async def acquire(self) -> FakeConnection:
        return self.connection

    async def release(self, connection: FakeConnection) -> None:
        self.released += 1
        if not connection.is_closed() and self.reset_fails:
            connection.terminate()
            raise asyncpg.InternalClientError(
                "cannot switch to state 15; another operation (2) is in progress"
            )


def rows() -> list[SpanRow]:
    request = export_request({"orders": 2})
    return normalize(request, 1, now_ns=1_700_000_100 * 10**9, accept_past_s=10**9, accept_future_s=600).rows


def store(connection: FakeConnection, reset_fails: bool = True) -> tuple[SpanStore, FakePool]:
    pool = FakePool(connection, reset_fails)
    return SpanStore(pool), pool  # type: ignore[arg-type]


async def test_servidor_desligando_no_meio_sobe_o_erro_original_e_descarta_a_conexao() -> None:
    connection = FakeConnection(
        asyncpg.AdminShutdownError("terminating connection due to administrator command")
    )
    s, pool = store(connection)
    with pytest.raises(asyncpg.AdminShutdownError) as raised:
        await s.insert(rows())
    assert isinstance(raised.value, TRANSIENT_DB_ERRORS)  # o processador vai esperar e repetir
    assert connection.terminated and pool.released == 1  # descartada, e a vaga do pool liberada


async def test_conexao_que_ja_caiu_vira_erro_de_conexao() -> None:
    bug_ou_queda = asyncpg.InternalClientError("cannot switch to state 15")
    s, _ = store(FakeConnection(bug_ou_queda, closed=True))
    with pytest.raises(asyncpg.ConnectionDoesNotExistError):
        await s.insert(rows())


async def test_bug_do_cliente_com_a_conexao_aberta_nao_e_mascarado() -> None:
    # Mesmo tipo de erro, mas a conexão continua aberta: é bug (como o do JSONB), não queda.
    s, _ = store(FakeConnection(asyncpg.InternalClientError("no binary format encoder for type jsonb")))
    with pytest.raises(asyncpg.InternalClientError) as raised:
        await s.insert(rows())
    assert not isinstance(raised.value, TRANSIENT_DB_ERRORS)  # sobe e derruba o processo, visível


async def test_erro_de_dado_mantem_a_conexao_no_pool() -> None:
    connection = FakeConnection(asyncpg.DataError("valor inválido"))
    s, pool = store(connection, reset_fails=False)
    with pytest.raises(asyncpg.DataError):
        await s.insert(rows())
    assert not connection.terminated and pool.released == 1  # conexão boa, reaproveitada

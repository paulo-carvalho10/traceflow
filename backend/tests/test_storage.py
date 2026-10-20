"""Gravação no TimescaleDB de verdade. Precisa do banco rodando:

    docker compose up -d timescaledb

Cria um banco descartável (traceflow_test), aplica as migrações e apaga no fim.
Sem o banco, os testes são pulados.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import asyncpg
import pytest
from alembic import command
from helpers import export_request

from traceflow.migrate import alembic_config
from traceflow.normalize import SpanRow, normalize
from traceflow.storage import TRANSIENT_DB_ERRORS, SpanStore

pytestmark = pytest.mark.db

ADMIN_DSN = os.environ.get(
    "TRACEFLOW_TEST_ADMIN_DSN", "postgresql://traceflow:traceflow@localhost:5432/postgres"
)
TEST_DB = "traceflow_test"
TEST_DSN = ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB}"
NOW_NS = 1_700_000_100_000_000_000


@pytest.fixture
async def store() -> AsyncIterator[SpanStore]:
    try:
        admin = await asyncpg.connect(ADMIN_DSN, timeout=3)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"TimescaleDB indisponível: {exc}")
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    # o Alembic roda o próprio laço asyncio, então vai para outra thread
    url = TEST_DSN.replace("postgresql://", "postgresql+asyncpg://", 1)
    await asyncio.to_thread(command.upgrade, alembic_config(url), "head")
    s = await SpanStore.connect(TEST_DSN)
    yield s
    await s.close()
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    await admin.close()


def rows(spans: int, project_id: int = 1) -> list[SpanRow]:
    request = export_request({"orders": spans})
    return normalize(request, project_id, now_ns=NOW_NS, accept_past_s=10**9, accept_future_s=600).rows


async def test_migracao_cria_hypertable_retencao_e_projeto_demo(store: SpanStore) -> None:
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM timescaledb_information.hypertables "
                                "WHERE hypertable_name = 'spans'") == 1  # fmt: skip
        assert await c.fetchval("SELECT count(*) FROM timescaledb_information.jobs "
                                "WHERE proc_name = 'policy_retention'") == 1  # fmt: skip
        assert await c.fetchval("SELECT slug FROM projects WHERE id = 1") == "demo"


async def test_gravar_duas_vezes_nao_duplica(store: SpanStore) -> None:
    lote = rows(5)
    assert await store.insert(lote) == 5
    assert await store.insert(lote) == 0  # reenvio: ON CONFLICT DO NOTHING
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM spans") == 5


async def test_mesmo_span_em_outro_projeto_nao_e_bloqueado(store: SpanStore) -> None:
    assert await store.insert(rows(2, project_id=1)) == 2
    assert await store.insert(rows(2, project_id=2)) == 2


async def test_jsonb_e_colunas_voltam_como_foram(store: SpanStore) -> None:
    [row] = rows(1)
    await store.insert([row])
    async with store.pool.acquire() as c:
        db = await c.fetchrow("SELECT * FROM spans")
    assert db is not None
    assert db["trace_id"] == row.trace_id and db["service"] == "orders"
    assert db["start_time"] == row.start_time and db["duration_ms"] == 50.0
    assert db["attributes"] == {} and db["events"] == []


async def test_conexao_derrubada_vira_erro_passageiro_e_a_proxima_gravacao_funciona(store: SpanStore) -> None:
    assert await store.insert(rows(1)) == 1
    # o banco derruba a conexão do pool por fora, como numa queda ou reinício do servidor
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = $1 AND pid <> pg_backend_pid()",
        TEST_DB,
    )
    await admin.close()
    outro_trace = normalize(
        export_request({"orders": 2}, trace_id=b"\x07" * 16),
        1, now_ns=NOW_NS, accept_past_s=10**9, accept_future_s=600,
    ).rows  # fmt: skip
    with pytest.raises(TRANSIENT_DB_ERRORS):  # o processador sabe esperar e tentar de novo
        await store.insert(outro_trace)
    assert await store.insert(outro_trace) == 2  # o pool trocou a conexão morta por uma nova

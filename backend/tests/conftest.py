"""O banco de teste: criado e migrado uma vez por execução, limpo antes de cada teste que o usa.

Precisa do TimescaleDB rodando (docker compose up -d timescaledb). Sem ele, os testes
que pedem o banco são pulados.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from alembic import command

from traceflow.migrate import alembic_config

ADMIN_DSN = os.environ.get(
    "TRACEFLOW_TEST_ADMIN_DSN", "postgresql://traceflow:traceflow@localhost:5432/postgres"
)
TEST_DB = "traceflow_test"
TEST_DSN = ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB}"

# Tudo o que os testes criam; o projeto demo e o visitante (das migrações) ficam.
CLEAN = """
TRUNCATE spans, api_keys, services, service_addresses;
DELETE FROM projects WHERE NOT is_demo;
DELETE FROM users WHERE NOT is_demo_visitor;
"""


async def _admin(sql: str) -> None:
    admin = await asyncpg.connect(ADMIN_DSN, timeout=3)
    try:
        await admin.execute(sql)
    finally:
        await admin.close()


@pytest.fixture(scope="session")
def database_dsn() -> Iterator[str]:
    try:
        asyncio.run(_admin(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        asyncio.run(_admin(f"CREATE DATABASE {TEST_DB}"))
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"TimescaleDB indisponível: {exc}")
    command.upgrade(alembic_config(TEST_DSN.replace("postgresql://", "postgresql+asyncpg://", 1)), "head")
    yield TEST_DSN
    asyncio.run(_admin(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))


@pytest.fixture
async def clean_db(database_dsn: str) -> AsyncIterator[str]:
    connection = await asyncpg.connect(database_dsn)
    try:
        await connection.execute(CLEAN)
    finally:
        await connection.close()
    yield database_dsn

"""Gravação no TimescaleDB de verdade (banco de teste do conftest.py; sem o banco, são pulados)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncpg
import pytest
from conftest import ADMIN_DSN, TEST_DB
from helpers import export_request

from traceflow.normalize import SpanRow, normalize
from traceflow.storage import TRANSIENT_DB_ERRORS, SpanStore

pytestmark = pytest.mark.db

NOW_NS = 1_700_000_100_000_000_000


@pytest.fixture
async def store(clean_db: str) -> AsyncIterator[SpanStore]:
    s = await SpanStore.connect(clean_db)
    yield s
    await s.close()


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
    # Dois desfechos certos, e qual acontece é corrida de rede: se o asyncpg ainda não percebeu a
    # queda, ele usa a conexão morta e o erro tem de ser passageiro (o processador espera e tenta
    # de novo, D28); se já percebeu, o pool troca a conexão em silêncio. No Docker Desktop do
    # Windows dava sempre o primeiro, no CI (Linux, tudo local) o segundo. Errado seria qualquer
    # outro erro, que travaria a fila.
    try:
        written = await store.insert(outro_trace)
    except TRANSIENT_DB_ERRORS:
        written = await store.insert(outro_trace)  # o pool já trocou a conexão morta por uma nova
    assert written == 2


async def test_catalogo_de_servicos_guarda_a_ultima_vez_visto(store: SpanStore) -> None:
    antes, depois = datetime(2026, 10, 20, 10, tzinfo=UTC), datetime(2026, 10, 20, 11, tzinfo=UTC)
    await store.upsert_services([(1, "demo", "orders", depois), (1, "demo", "payments", antes)])
    await store.upsert_services([(1, "demo", "orders", antes)])  # chegou atrasado: não volta no tempo
    async with store.pool.acquire() as c:
        linhas = await c.fetch("SELECT name, first_seen, last_seen FROM services ORDER BY name")
    assert [(r["name"], r["last_seen"]) for r in linhas] == [("orders", depois), ("payments", antes)]

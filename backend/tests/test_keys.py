"""O verificador de chaves da ingestão, com um banco de mentira e um relógio controlado."""

from __future__ import annotations

import asyncio

import pytest

from traceflow.ingest.keys import MAX_CACHED_KEYS, KeyRecord, KeyUnavailable, KeyVerifier
from traceflow.security import generate_key

KEY = generate_key()
AUTH = f"Bearer {KEY.full}"


class FakeLookup:
    def __init__(self) -> None:
        self.records: dict[str, KeyRecord] = {KEY.prefix: KeyRecord(7, KEY.secret_hash, revoked=False)}
        self.down = False
        self.finds = 0
        self.touched: list[str] = []

    async def find(self, prefix: str) -> KeyRecord | None:
        self.finds += 1
        await asyncio.sleep(0)  # devolve a vez, como uma consulta de verdade ao banco
        if self.down:
            raise OSError("banco fora")
        return self.records.get(prefix)

    async def touch(self, prefix: str) -> None:
        self.touched.append(prefix)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def lookup() -> FakeLookup:
    return FakeLookup()


@pytest.fixture
def clock() -> Clock:
    return Clock()


def verifier(lookup: FakeLookup, clock: Clock) -> KeyVerifier:
    return KeyVerifier(lookup, ttl_s=60, negative_ttl_s=10, clock=clock)


async def test_chave_valida_da_o_projeto_e_o_cache_poupa_o_banco(lookup: FakeLookup, clock: Clock) -> None:
    v = verifier(lookup, clock)
    for _ in range(100):
        assert await v.project_for(AUTH) == 7
    assert lookup.finds == 1  # 100 lotes, uma consulta
    assert lookup.touched == [KEY.prefix]  # "usada por último" registrado uma vez


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer tf_curta", f"Token {KEY.full}"])
async def test_sem_chave_ou_formato_errado_nem_consulta_o_banco(
    lookup: FakeLookup, clock: Clock, header: str | None
) -> None:
    assert await verifier(lookup, clock).project_for(header) is None
    assert lookup.finds == 0


async def test_segredo_errado_com_prefixo_certo_e_recusado(lookup: FakeLookup, clock: Clock) -> None:
    wrong = f"Bearer tf_{KEY.prefix}_{'x' * 32}"
    assert await verifier(lookup, clock).project_for(wrong) is None


async def test_revogacao_vale_quando_o_cache_vence(lookup: FakeLookup, clock: Clock) -> None:
    v = verifier(lookup, clock)
    assert await v.project_for(AUTH) == 7
    lookup.records[KEY.prefix] = KeyRecord(7, KEY.secret_hash, revoked=True)
    clock.now += 59
    assert await v.project_for(AUTH) == 7  # ainda no cache: é o atraso aceito de até 60 s
    clock.now += 2
    assert await v.project_for(AUTH) is None


async def test_chave_inexistente_fica_no_cache_negativo(lookup: FakeLookup, clock: Clock) -> None:
    v = verifier(lookup, clock)
    stranger = f"Bearer {generate_key().full}"
    for _ in range(50):
        assert await v.project_for(stranger) is None
    assert lookup.finds == 1  # alguém insistindo com chave errada não martela o banco
    clock.now += 11
    await v.project_for(stranger)
    assert lookup.finds == 2


async def test_banco_fora_sem_cache_e_503_nao_401(lookup: FakeLookup, clock: Clock) -> None:
    lookup.down = True
    with pytest.raises(KeyUnavailable):
        await verifier(lookup, clock).project_for(AUTH)


async def test_banco_fora_com_a_chave_ja_conhecida_continua_aceitando(
    lookup: FakeLookup, clock: Clock
) -> None:
    v = verifier(lookup, clock)
    assert await v.project_for(AUTH) == 7
    lookup.down = True
    clock.now += 600  # o cache já venceu faz tempo
    finds = lookup.finds
    for _ in range(50):
        assert await v.project_for(AUTH) == 7
    assert lookup.finds == finds + 1  # durante a queda, não tenta o banco a cada lote
    clock.now += 11
    await v.project_for(AUTH)
    assert lookup.finds == finds + 2  # tenta de novo depois de um intervalo


async def test_cache_nao_cresce_sem_limite(lookup: FakeLookup, clock: Clock) -> None:
    v = verifier(lookup, clock)
    for _ in range(MAX_CACHED_KEYS + 5):
        await v.project_for(f"Bearer {generate_key().full}")
    assert len(v._cache) <= MAX_CACHED_KEYS


async def test_varios_lotes_juntos_com_o_cache_vencido_fazem_uma_consulta_so(
    lookup: FakeLookup, clock: Clock
) -> None:
    v = verifier(lookup, clock)
    results = await asyncio.gather(*(v.project_for(AUTH) for _ in range(50)))
    assert results == [7] * 50
    assert lookup.finds == 1  # o "estouro de cache" evitado: 50 lotes, uma ida ao banco
    clock.now += 61
    await asyncio.gather(*(v.project_for(AUTH) for _ in range(50)))
    assert lookup.finds == 2


async def test_banco_fora_com_varios_lotes_juntos_da_503_para_todos(lookup: FakeLookup, clock: Clock) -> None:
    lookup.down = True
    v = verifier(lookup, clock)
    results = await asyncio.gather(*(v.project_for(AUTH) for _ in range(10)), return_exceptions=True)
    assert all(isinstance(r, KeyUnavailable) for r in results)
    assert lookup.finds == 1

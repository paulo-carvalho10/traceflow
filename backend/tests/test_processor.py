"""O processador com um Redis de mentira (fakeredis) e um banco de mentira (FakeStore)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any, cast

import asyncpg
import pytest
from fakeredis import FakeAsyncRedis
from helpers import export_request

from traceflow.config import Settings
from traceflow.normalize import SpanRow
from traceflow.processor.app import Processor
from traceflow.streams import DEAD_LETTER_STREAM, PROCESSORS_GROUP, SPANS_STREAM, SpanBatch

# o helpers.export_request usa spans de 2023; o "agora" do processador acompanha
NOW_NS = 1_700_000_100_000_000_000


class FakeStore:
    """Guarda as identidades gravadas e ignora repetidas, como o ON CONFLICT DO NOTHING."""

    def __init__(self, failures: int = 0, poison: str | None = None) -> None:
        self.poison = poison  # span_id que o "banco" recusa
        self.saved: set[tuple[int, str, str]] = set()
        self.catalog: list[tuple[int, str, str, datetime]] = []
        self.addresses: list[tuple[int, str, str, str, datetime]] = []
        self.preloaded: list[tuple[int, str, str, str]] = []
        self.rules: list[dict[str, Any]] = []
        self.incidents: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.failures = failures
        self.calls = 0

    async def upsert_services(self, seen: Sequence[tuple[int, str, str, datetime]]) -> None:
        self.catalog.extend(seen)

    async def upsert_addresses(self, learned: Sequence[tuple[int, str, str, str, datetime]]) -> None:
        self.addresses.extend(learned)

    async def load_addresses(self) -> list[tuple[int, str, str, str]]:
        return list(self.preloaded)

    async def load_rules(self) -> list[dict[str, Any]]:
        return list(self.rules)

    async def save_incident(self, row: dict[str, Any], events: Sequence[dict[str, Any]]) -> None:
        if self.failures:
            self.failures -= 1
            raise OSError("conexão recusada")
        self.incidents[row["id"]] = row
        self.events.extend(events)

    async def load_open_incidents(self) -> list[dict[str, Any]]:
        return [r for r in self.incidents.values() if r["status"] == "open"]

    async def insert(self, rows: Sequence[SpanRow]) -> int:
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise OSError("conexão recusada")
        if any(r.span_id == self.poison for r in rows):
            raise asyncpg.DataError("valor inválido para o tipo")
        before = len(self.saved)
        self.saved.update((r.project_id, r.trace_id, r.span_id) for r in rows)
        return len(self.saved) - before


@pytest.fixture
async def fake_redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    yield client
    await client.aclose()


def settings(**overrides: object) -> Settings:
    return Settings(accept_past_s=10**9, **overrides)  # type: ignore[arg-type]


def processor(redis: FakeAsyncRedis, store: FakeStore, **overrides: object) -> Processor:
    async def no_sleep(_: float) -> None:
        return None

    return Processor(redis, store, settings(**overrides), clock_ns=lambda: NOW_NS, sleep=no_sleep)


async def enqueue(redis: FakeAsyncRedis, spans: int, project_id: int = 1, trace: int | None = None) -> None:
    """Põe um lote na fila. Cada lote é um trace diferente, a menos que `trace` repita um."""
    trace = trace if trace is not None else await redis.incr("teste:trace")
    body = export_request({"orders": spans}, trace_id=trace.to_bytes(16, "big")).SerializeToString()
    batch = SpanBatch(
        project_id=project_id, received_at_ms=NOW_NS // 1_000_000 - 50, span_count=spans, payload=body
    )
    await redis.xadd(SPANS_STREAM, batch.to_fields())  # type: ignore[arg-type]


async def pending(redis: FakeAsyncRedis) -> int:
    info = await redis.xpending(SPANS_STREAM, PROCESSORS_GROUP)
    return int(info["pending"])


async def test_grava_confirma_e_tira_da_fila(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore()
    p = processor(fake_redis, store)
    await p.ensure_group()
    await enqueue(fake_redis, 3)
    await enqueue(fake_redis, 2)
    await p.handle(await p.read(">"))
    assert len(store.saved) == 5
    assert await fake_redis.xlen(SPANS_STREAM) == 0  # XDEL: a fila é só o que falta
    assert await pending(fake_redis) == 0  # XACK
    assert (p.stats.spans_written, p.stats.batches, p.stats.lag_ms_sum) == (5, 2, 100)


async def test_lote_repetido_nao_duplica(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore()
    p = processor(fake_redis, store)
    await p.ensure_group()
    await enqueue(fake_redis, 3, trace=99)
    await enqueue(fake_redis, 3, trace=99)  # o mesmo conteúdo de novo, como num reenvio
    await p.handle(await p.read(">"))
    assert (p.stats.spans_written, p.stats.duplicates) == (3, 3)


async def test_banco_fora_nao_confirma_ate_conseguir_gravar(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore(failures=3)
    waits: list[float] = []
    pending_during_failure: list[int] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        pending_during_failure.append(await pending(fake_redis))

    p = Processor(fake_redis, store, settings(), clock_ns=lambda: NOW_NS, sleep=sleep)
    await p.ensure_group()
    await enqueue(fake_redis, 4)
    await p.handle(await p.read(">"))
    assert waits == [0.5, 1.0, 2.0]  # espera crescente
    assert pending_during_failure == [1, 1, 1]  # enquanto falhava, o lote seguia pendente
    assert len(store.saved) == 4 and await pending(fake_redis) == 0
    assert p.stats.write_retries == 3


async def test_lote_ilegivel_vai_para_o_stream_de_mortos_e_nao_trava_a_fila(
    fake_redis: FakeAsyncRedis,
) -> None:
    store = FakeStore()
    p = processor(fake_redis, store)
    await p.ensure_group()
    await enqueue(fake_redis, 2)
    await fake_redis.xadd(SPANS_STREAM, {"project_id": "1", "received_at_ms": "0", "span_count": "1",
                                         "payload": b"\xff\xff lixo"})  # fmt: skip
    await enqueue(fake_redis, 1)
    await p.handle(await p.read(">"))
    assert len(store.saved) == 3  # os bons foram gravados
    [(_, dead)] = cast(list[tuple[bytes, dict[bytes, bytes]]], await fake_redis.xrange(DEAD_LETTER_STREAM))
    assert dead[b"payload"] == b"\xff\xff lixo"
    assert b"DecodeError" in dead[b"error"]
    assert await fake_redis.xlen(SPANS_STREAM) == 0 and await pending(fake_redis) == 0


async def test_consumidor_que_caiu_tem_os_pendentes_assumidos(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore()
    morto = processor(fake_redis, store, consumer_name="processor-velho")
    await morto.ensure_group()
    await enqueue(fake_redis, 2)
    await morto.read(">")  # leu e "caiu" antes de gravar
    assert await pending(fake_redis) == 1

    novo = processor(fake_redis, store, consumer_name="processor-novo", reclaim_idle_ms=0)
    assert await novo.reclaim() == 1
    assert len(store.saved) == 2 and await pending(fake_redis) == 0


async def test_ao_reiniciar_termina_os_proprios_pendentes(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore()
    antes = processor(fake_redis, store)
    await antes.ensure_group()
    await enqueue(fake_redis, 2)
    await antes.read(">")  # leu e caiu

    depois = processor(fake_redis, store)  # mesmo nome de consumidor
    await depois.ensure_group()  # o grupo já existe: não pode dar erro
    await depois.recover_own_pending()
    assert len(store.saved) == 2 and await pending(fake_redis) == 0


async def test_spans_fora_da_janela_sao_contados(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore()
    p = Processor(fake_redis, store, Settings(accept_past_s=60), clock_ns=lambda: NOW_NS)
    await p.ensure_group()
    await enqueue(fake_redis, 3)  # spans de 100 s atrás, janela de 60 s
    await p.handle(await p.read(">"))
    assert (len(store.saved), p.stats.out_of_window) == (0, 3)
    assert await fake_redis.xlen(SPANS_STREAM) == 0  # mesmo sem nada gravado, o lote foi tratado


async def test_linha_que_o_banco_recusa_e_isolada_e_o_resto_e_gravado(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore(poison="0000000000000005")  # o 5º span de cada lote
    p = processor(fake_redis, store)
    await p.ensure_group()
    await enqueue(fake_redis, 8)
    await p.handle(await p.read(">"))
    assert len(store.saved) == 7  # só o envenenado ficou de fora
    assert (p.stats.rejected_rows, p.stats.duplicates, p.stats.write_retries) == (1, 0, 0)
    assert store.calls == 7  # 8 -> 4+4 -> 2+2 -> 1+1: poucas idas ao banco, não uma por linha
    assert await pending(fake_redis) == 0


async def test_catalogo_registra_cada_servico_uma_vez_por_minuto(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore()
    p = processor(fake_redis, store)
    await p.ensure_group()
    for _ in range(3):
        await enqueue(fake_redis, 2)
        await p.handle(await p.read(">"))
    assert [(proj, env, name) for proj, env, name, _ in store.catalog] == [(1, "default", "orders")]


async def test_duas_leituras_gravam_ao_mesmo_tempo(fake_redis: FakeAsyncRedis) -> None:
    """Com writers=2, enquanto uma gravação espera o banco, a outra leitura já está gravando."""

    class SlowStore(FakeStore):
        def __init__(self) -> None:
            super().__init__()
            self.now = self.most = 0

        async def insert(self, rows: Sequence[SpanRow]) -> int:
            self.now += 1
            self.most = max(self.most, self.now)
            await asyncio.sleep(0.05)  # o banco demorando
            self.now -= 1
            return await super().insert(rows)

    store = SlowStore()
    p = processor(fake_redis, store, read_count=1, read_block_ms=10)
    await p.ensure_group()
    for _ in range(4):
        await enqueue(fake_redis, 2)
    consumers = [asyncio.create_task(p.consume_forever()) for _ in range(2)]
    try:
        for _ in range(100):
            if len(store.saved) == 8:
                break
            await asyncio.sleep(0.02)
    finally:
        for task in consumers:
            task.cancel()
        await asyncio.gather(*consumers, return_exceptions=True)
    assert len(store.saved) == 8
    assert store.most == 2

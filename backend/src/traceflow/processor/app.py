"""O processador: tira os lotes da fila, normaliza os spans e grava no banco.

A regra de ouro: só confirmar (XACK) depois de gravar. Se o processo cair no meio,
o lote continua pendente no consumer group e é relido; como a gravação ignora o que já
existe, reler não duplica nada. É entrega "pelo menos uma vez" com gravação idempotente.

Depois de confirmar, a entrada é apagada (XDEL): o tamanho da fila passa a ser
exatamente o que falta processar, que é o número que a ingestão usa como freio.

Quatro tarefas rodam juntas:
    consume   lê entradas novas (">") e processa
    reclaim   pega pendentes largados por um consumidor que caiu (XAUTOCLAIM)
    publish   a cada segundo, publica o retrato ao vivo de cada projeto e ambiente
    report    escreve no log a vazão e o atraso, a cada 10 s
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

import asyncpg
import redis.asyncio as redis
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from traceflow.config import Settings, setup_logging
from traceflow.config import redis_client as make_redis_client
from traceflow.live.aggregator import LiveAggregator
from traceflow.normalize import SpanRow, normalize
from traceflow.storage import ANY_DB_ERROR, TRANSIENT_DB_ERRORS, SpanStore
from traceflow.streams import (
    DEAD_LETTER_STREAM,
    LIVE_CHANNEL,
    LIVE_TICK,
    PROCESSORS_GROUP,
    SNAPSHOT_TTL_S,
    SPANS_STREAM,
    SpanBatch,
    snapshot_key,
)

log = logging.getLogger("traceflow.processor")

Entry = tuple[bytes, dict[bytes, bytes] | None]


class Store(Protocol):
    async def insert(self, rows: Sequence[SpanRow]) -> int: ...
    async def upsert_services(self, seen: Sequence[tuple[int, str, str, datetime]]) -> None: ...


CATALOG_REFRESH_S = 60.0  # o "visto por último" de cada serviço é atualizado no máximo uma vez por minuto


@dataclass
class ProcessorStats:
    batches: int = 0
    spans_received: int = 0
    spans_written: int = 0
    duplicates: int = 0
    out_of_window: int = 0
    dead_letters: int = 0
    lag_ms_sum: int = 0
    write_retries: int = 0
    rejected_rows: int = 0  # linhas que o banco recusou, isoladas e descartadas


class Processor:
    def __init__(
        self,
        client: redis.Redis,
        store: Store,
        settings: Settings,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.redis = client
        self.store = store
        self.settings = settings
        self.clock_ns = clock_ns
        self.sleep = sleep
        self.stats = ProcessorStats()
        self._rejected_now = 0
        self._catalog_seen: dict[tuple[int, str, str], float] = {}  # serviço -> quando foi registrado
        self.live = LiveAggregator()

    async def ensure_group(self) -> None:
        """Cria o consumer group, se ainda não existir. O id "0" pega também o que já está na fila."""
        try:
            await self.redis.xgroup_create(SPANS_STREAM, PROCESSORS_GROUP, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read(self, start: str) -> list[Entry]:
        """start=">" lê só o que nunca foi entregue; start="0" relê os pendentes deste consumidor."""
        response = await self.redis.xreadgroup(
            PROCESSORS_GROUP,
            self.settings.consumer_name,
            {SPANS_STREAM: start},
            count=self.settings.read_count,
            block=self.settings.read_block_ms if start == ">" else None,
        )
        if not response:
            return []
        # [[stream, [(id, campos), ...]]]: uma fila só, então o primeiro item
        streams = cast(list[tuple[bytes, list[Entry]]], response)  # RESP2: lista de [fila, entradas]
        return streams[0][1]

    async def recover_own_pending(self) -> None:
        """Ao subir, termina o que este mesmo consumidor tinha lido e não confirmou antes de cair."""
        while entries := await self.read("0"):
            await self.handle(entries)

    async def reclaim(self) -> int:
        """Assume os pendentes parados há mais de reclaim_idle_ms, de qualquer consumidor."""
        _, entries, *_ = await self.redis.xautoclaim(
            SPANS_STREAM,
            PROCESSORS_GROUP,
            self.settings.consumer_name,
            min_idle_time=self.settings.reclaim_idle_ms,
            start_id="0-0",
            count=self.settings.read_count,
        )
        if entries:
            log.warning("assumi %d lotes pendentes largados por outro consumidor", len(entries))
            await self.handle(entries)
        return len(entries)

    async def handle(self, entries: Sequence[Entry]) -> None:
        rows: list[SpanRow] = []
        dead: list[tuple[bytes, dict[bytes, bytes], str]] = []
        now = self.clock_ns()
        for entry_id, fields in entries:
            if fields is None:  # a entrada já foi apagada: só falta confirmar
                continue
            try:
                batch = SpanBatch.from_fields(fields)
                export = ExportTraceServiceRequest.FromString(batch.payload)
            except (KeyError, ValueError, DecodeError) as exc:
                dead.append((entry_id, fields, f"{type(exc).__name__}: {exc}"))
                continue
            result = normalize(
                export,
                batch.project_id,
                now_ns=now,
                accept_past_s=self.settings.accept_past_s,
                accept_future_s=self.settings.accept_future_s,
            )
            rows.extend(result.rows)
            self.stats.out_of_window += result.out_of_window
            self.stats.spans_received += batch.span_count
            self.stats.lag_ms_sum += max(0, now // 1_000_000 - batch.received_at_ms)
            self.stats.batches += 1

        written = await self.write(rows)  # 1. grava (tenta até conseguir)
        await self.dead_letter(dead)
        ids = [entry_id for entry_id, _ in entries]
        pipe = self.redis.pipeline(transaction=False)
        pipe.xack(SPANS_STREAM, PROCESSORS_GROUP, *ids)  # 2. só então confirma
        pipe.xdel(SPANS_STREAM, *ids)  # 3. e tira da fila
        await pipe.execute()

        self.stats.spans_written += written
        self.stats.duplicates += len(rows) - written - self._rejected_now
        self._rejected_now = 0
        self.live.add(rows, now / 1e9)
        await self.update_catalog(rows)

    async def update_catalog(self, rows: Sequence[SpanRow]) -> None:
        """Mantém o catálogo de serviços. É de melhor esforço: se falhar, tenta no próximo lote.

        O catálogo é um índice auxiliar; a verdade são os spans. Por isso uma falha aqui
        nunca segura a fila nem desfaz a gravação.
        """
        now = time.monotonic()
        latest: dict[tuple[int, str, str], datetime] = {}
        for row in rows:
            key = (row.project_id, row.environment, row.service)
            if now - self._catalog_seen.get(key, -CATALOG_REFRESH_S) >= CATALOG_REFRESH_S:
                latest[key] = max(latest.get(key, row.start_time), row.start_time)
        if not latest:
            return
        try:
            await self.store.upsert_services([(*key, when) for key, when in latest.items()])
        except ANY_DB_ERROR as exc:
            log.warning("não consegui atualizar o catálogo de serviços (%s); fica para o próximo lote", exc)
            return
        for key in latest:
            self._catalog_seen[key] = now

    async def write(self, rows: Sequence[SpanRow]) -> int:
        """Grava, insistindo com espera crescente se o banco falhar.

        Enquanto o banco está fora, o processador não confirma nada e não lê mais nada:
        a fila cresce, e a ingestão começa a pedir para os exportadores esperarem.
        """
        delay = 0.5
        while True:
            try:
                return await self.insert_isolating_bad_rows(rows)
            except TRANSIENT_DB_ERRORS as exc:
                self.stats.write_retries += 1
                log.warning("falha ao gravar %d spans (%s); tentando de novo em %.1fs", len(rows), exc, delay)
                await self.sleep(delay)
                delay = min(delay * 2, 10.0)

    async def insert_isolating_bad_rows(self, rows: Sequence[SpanRow]) -> int:
        """Grava; se o banco recusar um dado, divide o lote ao meio até achar a linha culpada.

        Repetir um erro de dado não adianta: ele falharia para sempre e travaria a fila.
        Dividindo ao meio, uma linha ruim em 2000 é achada em cerca de 11 divisões
        (log2 de 2000), e as outras 1999 são gravadas.
        """
        try:
            return await self.store.insert(rows)
        except asyncpg.PostgresError as exc:
            if isinstance(exc, TRANSIENT_DB_ERRORS):
                raise
            if len(rows) == 1:
                [row] = rows
                log.error("span recusado pelo banco e descartado (trace %s, serviço %s): %s",
                          row.trace_id, row.service, exc)  # fmt: skip
                self.stats.rejected_rows += 1
                self._rejected_now += 1
                return 0
            middle = len(rows) // 2
            return await self.insert_isolating_bad_rows(rows[:middle]) + await self.insert_isolating_bad_rows(
                rows[middle:]
            )

    async def dead_letter(self, dead: Sequence[tuple[bytes, dict[bytes, bytes], str]]) -> None:
        """Lote ilegível não pode travar a fila: vai para o stream de mortos, com o motivo, e segue."""
        for entry_id, fields, reason in dead:
            log.error("lote %s ilegível, movido para %s: %s", entry_id.decode(), DEAD_LETTER_STREAM, reason)
            await self.redis.xadd(
                DEAD_LETTER_STREAM,
                {**fields, b"error": reason.encode(), b"original_id": entry_id},  # type: ignore[dict-item]
                maxlen=10_000,
                approximate=True,
            )
        self.stats.dead_letters += len(dead)

    async def consume_forever(self) -> None:
        while True:
            entries = await self.read(">")
            if entries:
                await self.handle(entries)

    async def reclaim_forever(self) -> None:
        while True:
            await self.sleep(self.settings.reclaim_every_s)
            try:
                await self.reclaim()
            except redis.RedisError as exc:
                log.warning("não consegui verificar pendentes: %s", exc)

    async def publish_live(self) -> int:
        """Grava e anuncia o retrato de cada projeto e ambiente, e o tique. Devolve quantos retratos."""
        snapshots = self.live.snapshots(self.clock_ns() / 1e9)
        pipe = self.redis.pipeline(transaction=False)
        for (project, environment), snapshot in snapshots.items():
            payload = json.dumps(snapshot, separators=(",", ":"))
            pipe.set(snapshot_key(project, environment), payload, ex=SNAPSHOT_TTL_S)
            pipe.publish(LIVE_CHANNEL, payload)
        # por último, e mesmo sem retrato nenhum: a API sabe que todos os retratos deste
        # segundo já passaram, e avisa "sem tráfego" a quem não recebeu nenhum
        pipe.publish(LIVE_CHANNEL, LIVE_TICK)
        await pipe.execute()
        return len(snapshots)

    async def publish_forever(self) -> None:
        # O retrato é descartável: se um falhar, o próximo segundo traz outro mais novo.
        while True:
            await self.sleep(1.0)
            try:
                await self.publish_live()
            except redis.RedisError as exc:
                log.warning("não consegui publicar o retrato ao vivo: %s", exc)

    async def report_forever(self) -> None:
        every = self.settings.stats_every_s
        while True:
            before = ProcessorStats(**vars(self.stats))
            await self.sleep(every)
            s = self.stats
            batches = s.batches - before.batches
            try:
                backlog = await self.redis.xlen(SPANS_STREAM)
            except redis.RedisError:
                backlog = -1
            log.info(
                "%.0f spans/s gravados, %d repetidos, %d fora da janela, %d recusados, %d lotes mortos, "
                "atraso médio %.0f ms, fila=%d, total gravado=%d",
                (s.spans_written - before.spans_written) / every,
                s.duplicates - before.duplicates,
                s.out_of_window - before.out_of_window,
                s.rejected_rows - before.rejected_rows,
                s.dead_letters - before.dead_letters,
                (s.lag_ms_sum - before.lag_ms_sum) / batches if batches else 0,
                backlog,
                s.spans_written,
            )

    async def run(self) -> None:
        await self.ensure_group()
        await self.recover_own_pending()
        tasks = [
            asyncio.create_task(self.consume_forever()),
            asyncio.create_task(self.reclaim_forever()),
            asyncio.create_task(self.publish_forever()),
            asyncio.create_task(self.report_forever()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task


async def amain(settings: Settings) -> None:
    client = make_redis_client(settings.redis_url)
    store = await connect_with_retry(settings.database_url)
    log.info("processador %s conectado; lendo %s", settings.consumer_name, SPANS_STREAM)
    try:
        await Processor(client, store, settings).run()
    finally:
        await store.close()
        await client.aclose()


async def connect_with_retry(dsn: str) -> SpanStore:
    delay = 0.5
    while True:
        try:
            return await SpanStore.connect(dsn)
        except TRANSIENT_DB_ERRORS as exc:
            log.warning("banco indisponível (%s); tentando de novo em %.1fs", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10.0)


def main() -> None:
    setup_logging()
    with suppress(KeyboardInterrupt):
        asyncio.run(amain(Settings()))


if __name__ == "__main__":
    main()

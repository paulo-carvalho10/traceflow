"""O processador: tira os lotes da fila, normaliza os spans e grava no banco.

A regra de ouro: só confirmar (XACK) depois de gravar. Se o processo cair no meio,
o lote continua pendente no consumer group e é relido; como a gravação ignora o que já
existe, reler não duplica nada. É entrega "pelo menos uma vez" com gravação idempotente.

Depois de confirmar, a entrada é apagada (XDEL): o tamanho da fila passa a ser
exatamente o que falta processar, que é o número que a ingestão usa como freio.

Quatro tarefas rodam juntas:
    consume   lê entradas novas (">") e processa; são `writers` cópias (2 por padrão): enquanto
              uma espera o banco gravar, a outra já normaliza a leitura seguinte (D66)
    reclaim   pega pendentes largados por um consumidor que caiu (XAUTOCLAIM)
    publish   a cada segundo, publica o retrato ao vivo de cada projeto e ambiente
    report    escreve no log a vazão e o atraso, a cada 10 s

As métricas (Prometheus) ficam numa porta interna, em GET /metrics (traceflow.prometheus).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import asyncpg
import redis.asyncio as redis
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from prometheus_client import Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.metrics_core import Metric

from traceflow.config import Settings, setup_logging
from traceflow.config import redis_client as make_redis_client
from traceflow.incidents.engine import Assessor
from traceflow.incidents.rules import DEFAULT_RULES, Rule
from traceflow.incidents.text import reason as health_reason
from traceflow.incidents.tracker import Incident, IncidentTracker
from traceflow.live.aggregator import LiveAggregator
from traceflow.live.topology import AddressBook, AddressKey, Learned
from traceflow.normalize import SpanRow, normalize
from traceflow.prometheus import LATENCY_BUCKETS, Reading, new_registry, serve
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
    async def upsert_addresses(self, learned: Sequence[tuple[int, str, str, str, datetime]]) -> None: ...
    async def load_addresses(self) -> list[tuple[int, str, str, str]]: ...
    async def load_rules(self) -> Sequence[Any]: ...
    async def save_incident(self, row: dict[str, Any], events: Sequence[dict[str, Any]]) -> None: ...
    async def load_open_incidents(self) -> Sequence[Any]: ...


CATALOG_REFRESH_S = 60.0  # o "visto por último" de cada serviço é atualizado no máximo uma vez por minuto
RULES_REFRESH_S = 10.0  # uma regra editada na tela vale em até 10 s


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


STATS_METRICS = {
    "batches": "Lotes lidos da fila",
    "spans_received": "Spans que chegaram nos lotes",
    "spans_written": "Spans novos gravados no banco",
    "duplicates": "Spans repetidos, ignorados na gravação (entrega pelo menos uma vez)",
    "out_of_window": "Spans descartados por estarem fora da janela de tempo aceita",
    "dead_letters": "Lotes ilegíveis, movidos para a fila de mortos",
    "write_retries": "Novas tentativas de gravação depois de uma falha do banco",
    "rejected_rows": "Spans recusados pelo banco, isolados e descartados",
}


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
        self._catalog_seen: dict[tuple[int, str, str], float] = {}  # serviço -> quando foi registrado
        self.live = LiveAggregator()
        self.addresses = AddressBook()
        # endereço -> (quando foi gravado, qual serviço): grava de novo se mudou ou depois de 1 min
        self._addresses_saved: dict[AddressKey, tuple[float, str]] = {}
        self.assessor = Assessor()
        self.incidents = IncidentTracker()
        self.rules: dict[int, list[Rule]] | None = None  # None: ainda não carregou (vale o padrão)
        self._rules_at = -RULES_REFRESH_S
        self.registry = new_registry()
        self.registry.register(Reading(self.metrics))
        self.lag = Histogram(
            "traceflow_processor_lag_seconds",
            "Do recebimento na ingestão até a gravação no banco, por lote",
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.write_seconds = Histogram(
            "traceflow_processor_write_seconds",
            "Quanto leva gravar uma leitura da fila, com as novas tentativas",
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.snapshot_seconds = Histogram(
            "traceflow_processor_snapshot_seconds",
            "Quanto leva o retrato de cada segundo: agregar, avaliar e publicar",
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )

    def metrics(self) -> Iterator[Metric]:
        for name, doc in STATS_METRICS.items():
            yield CounterMetricFamily(f"traceflow_processor_{name}", doc, value=getattr(self.stats, name))
        yield GaugeMetricFamily(
            "traceflow_incidents_open", "Incidentes abertos agora", value=len(self.incidents.open)
        )
        yield GaugeMetricFamily(
            "traceflow_processor_pairs_waiting",
            "Chamadas CLIENT ou SERVER esperando o par (mapa de serviços)",
            value=self.addresses.waiting,
        )

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
        received_at_ms: list[int] = []
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
            received_at_ms.append(batch.received_at_ms)

        started = time.perf_counter()
        written, rejected = await self.write(rows)  # 1. grava (tenta até conseguir)
        self.write_seconds.observe(time.perf_counter() - started)
        await self.dead_letter(dead)
        ids = [entry_id for entry_id, _ in entries]
        pipe = self.redis.pipeline(transaction=False)
        pipe.xack(SPANS_STREAM, PROCESSORS_GROUP, *ids)  # 2. só então confirma
        pipe.xdel(SPANS_STREAM, *ids)  # 3. e tira da fila
        await pipe.execute()
        # o atraso do pipeline: do lote chegar na ingestão até estar no banco
        done_ms = self.clock_ns() // 1_000_000
        for received in received_at_ms:
            self.lag.observe(max(0, done_ms - received) / 1000)

        self.stats.spans_written += written
        self.stats.rejected_rows += rejected
        self.stats.duplicates += len(rows) - written - rejected
        self.live.add(rows, now / 1e9)
        paired = self.addresses.observe(rows, now / 1e9)
        await self.update_catalog(rows)
        await self.update_addresses(paired, datetime.fromtimestamp(now / 1e9, tz=UTC))

    async def update_addresses(self, paired: Sequence[Learned], when: datetime) -> None:
        """Grava o catálogo de endereços. Melhor esforço, como o de serviços.

        Grava o que é novo, o que mudou de serviço, e o resto no máximo uma vez por minuto
        (o "visto por último"). Se falhar, o que está em memória continua valendo.
        """
        now = time.monotonic()
        due = []
        for project_id, environment, address, service in paired:
            saved = self._addresses_saved.get((project_id, environment, address))
            if saved is None or saved[1] != service or now - saved[0] >= CATALOG_REFRESH_S:
                due.append((project_id, environment, address, service))
        if not due:
            return
        try:
            await self.store.upsert_addresses([(*entry, when) for entry in due])
        except ANY_DB_ERROR as exc:
            log.warning("não consegui gravar o catálogo de endereços (%s); fica para o próximo lote", exc)
            return
        for project_id, environment, address, service in due:
            self._addresses_saved[(project_id, environment, address)] = (now, service)

    async def load_addresses(self) -> None:
        """Começa sabendo o que já foi aprendido. Sem o banco, começa do zero e reaprende com o tráfego."""
        try:
            known = await self.store.load_addresses()
        except ANY_DB_ERROR as exc:
            log.warning("não consegui carregar o catálogo de endereços (%s); ele se refaz com o tráfego", exc)
            return
        self.addresses.load(known)
        log.info("catálogo de endereços carregado: %d endereços", len(known))

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

    async def write(self, rows: Sequence[SpanRow]) -> tuple[int, int]:
        """Grava, insistindo com espera crescente se o banco falhar. Devolve (novos, recusados).

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

    async def insert_isolating_bad_rows(self, rows: Sequence[SpanRow]) -> tuple[int, int]:
        """Grava; se o banco recusar um dado, divide o lote ao meio até achar a linha culpada.

        Repetir um erro de dado não adianta: ele falharia para sempre e travaria a fila.
        Dividindo ao meio, uma linha ruim em 2000 é achada em cerca de 11 divisões
        (log2 de 2000), e as outras 1999 são gravadas. Devolve (novos, recusados): a contagem
        é desta gravação, e não do objeto, porque duas gravações podem correr juntas.
        """
        try:
            return await self.store.insert(rows), 0
        except asyncpg.PostgresError as exc:
            if isinstance(exc, TRANSIENT_DB_ERRORS):
                raise
            if len(rows) == 1:
                [row] = rows
                log.error("span recusado pelo banco e descartado (trace %s, serviço %s): %s",
                          row.trace_id, row.service, exc)  # fmt: skip
                return 0, 1
            middle = len(rows) // 2
            first = await self.insert_isolating_bad_rows(rows[:middle])
            second = await self.insert_isolating_bad_rows(rows[middle:])
            return first[0] + second[0], first[1] + second[1]

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
        now = self.clock_ns() / 1e9
        snapshots = self.live.snapshots(now, self.addresses.resolve)
        await self.refresh_rules()
        self.assess(snapshots, now)
        pipe = self.redis.pipeline(transaction=False)
        for (project, environment), snapshot in snapshots.items():
            payload = json.dumps(snapshot, separators=(",", ":"))
            pipe.set(snapshot_key(project, environment), payload, ex=SNAPSHOT_TTL_S)
            pipe.publish(LIVE_CHANNEL, payload)
        # por último, e mesmo sem retrato nenhum: a API sabe que todos os retratos deste
        # segundo já passaram, e avisa "sem tráfego" a quem não recebeu nenhum
        pipe.publish(LIVE_CHANNEL, LIVE_TICK)
        await pipe.execute()
        await self.save_incidents()
        return len(snapshots)

    def assess(self, snapshots: dict[tuple[int, str], dict[str, Any]], now: float) -> None:
        """Saúde, causa e incidente de cada projeto e ambiente; tudo vai junto no retrato."""
        for channel, snapshot in snapshots.items():
            open_now = channel in self.incidents.open
            # a linha de base das rotas de entrada não aprende durante um incidente
            assessment = self.assessor.assess(
                snapshot, self.rules_for(channel[0]), now, learn_routes=not open_now
            )
            snapshot["health"] = {
                node: {"state": v.state, "reason": health_reason(v)}
                for node, v in assessment.verdicts.items()
                if v.state != "healthy"
            }
            incident = self.incidents.step(channel, assessment, now)
            snapshot["incident"] = incident.public() if incident and incident.status == "open" else None
        # um projeto que parou de mandar spans no meio de um incidente: sem dados, conta como saudável
        for channel in [c for c in self.incidents.open if c not in snapshots]:
            self.incidents.step(channel, None, now)

    def rules_for(self, project_id: int) -> list[Rule]:
        if self.rules is None:
            return list(DEFAULT_RULES)  # o banco não respondeu ainda: vale o padrão
        return self.rules.get(project_id, [])  # o dono pode ter desligado todas

    async def refresh_rules(self) -> None:
        now = time.monotonic()
        if now - self._rules_at < RULES_REFRESH_S:
            return
        self._rules_at = now
        try:
            records = await self.store.load_rules()
        except ANY_DB_ERROR as exc:
            log.warning("não consegui ler as regras (%s); seguem as que eu já tinha", exc)
            return
        rules: dict[int, list[Rule]] = defaultdict(list)
        for r in records:
            rules[r["project_id"]].append(
                Rule(
                    target=r["target"], metric=r["metric"], operator=r["operator"], threshold=r["threshold"],
                    state=r["state"], relative=r["relative"], min_requests=r["min_requests"], id=r["id"],
                )
            )  # fmt: skip
        self.rules = dict(rules)

    async def save_incidents(self) -> None:
        """Grava o que mudou nos incidentes. Se o banco falhar, fica para o próximo segundo."""
        for incident in list(self.incidents.unsaved.values()):
            if not (incident.dirty or incident.pending):
                self.incidents.unsaved.pop(incident.id, None)
                continue
            events = list(incident.pending)
            try:
                await self.store.save_incident(
                    incident.row(),
                    [
                        {"id": e.id, "at": datetime.fromtimestamp(e.at, tz=UTC), "kind": e.kind,
                         "message": e.message, "data": e.data}
                        for e in events
                    ],
                )  # fmt: skip
            except ANY_DB_ERROR as exc:
                log.warning(
                    "não consegui gravar o incidente %s (%s); tento no próximo segundo", incident.id, exc
                )
                return
            self.incidents.saved(incident, events)

    async def resume_incidents(self) -> None:
        """Retoma os incidentes que estavam abertos: o mesmo incidente continua, com o mesmo id."""
        try:
            records = await self.store.load_open_incidents()
        except ANY_DB_ERROR as exc:
            log.warning("não consegui ler os incidentes abertos (%s)", exc)
            return
        self.incidents.resume(
            [
                Incident(
                    project_id=r["project_id"], environment=r["environment"],
                    opened_at=r["opened_at"].timestamp(), severity=r["severity"],
                    peak_severity=r["peak_severity"], title=r["title"], causes=r["causes"],
                    affected=r["affected"], at_risk=r["at_risk"], endpoints=r["endpoints"], id=str(r["id"]),
                )
                for r in records
            ]
        )  # fmt: skip
        if records:
            log.info("retomando %d incidente(s) aberto(s)", len(records))

    async def publish_forever(self) -> None:
        # O retrato é descartável: se um falhar, o próximo segundo traz outro mais novo.
        while True:
            await self.sleep(1.0)
            started = time.perf_counter()
            try:
                await self.publish_live()
                self.snapshot_seconds.observe(time.perf_counter() - started)
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
                "atraso médio %.0f ms, fila=%d, total gravado=%d, esperando par=%d",
                (s.spans_written - before.spans_written) / every,
                s.duplicates - before.duplicates,
                s.out_of_window - before.out_of_window,
                s.rejected_rows - before.rejected_rows,
                s.dead_letters - before.dead_letters,
                (s.lag_ms_sum - before.lag_ms_sum) / batches if batches else 0,
                backlog,
                s.spans_written,
                self.addresses.waiting,
            )

    async def run(self) -> None:
        await self.ensure_group()
        await self.load_addresses()  # antes dos pendentes: eles já pareiam com o catálogo pronto
        await self.resume_incidents()
        await self.refresh_rules()
        await self.recover_own_pending()
        close_metrics = serve(self.registry, self.settings.metrics_port)
        tasks = [
            *(asyncio.create_task(self.consume_forever()) for _ in range(self.settings.writers)),
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
            close_metrics()


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

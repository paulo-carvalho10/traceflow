"""O teste de carga do pipeline: quantos spans por segundo a ingestão e o processador aguentam.

Ele manda traces sintéticos direto para a ingestão (OTLP/HTTP em protobuf), em degraus de
ritmo crescente, num projeto próprio ("Teste de carga"). Em cada degrau, anota o que o cliente
viu (aceitos, recusas por contrapressão, tempo de resposta) e o que o /metrics da ingestão e do
processador diz (spans gravados, tamanho da fila, atraso até o banco).

    docker compose up -d                      o TraceFlow, com o /metrics nas portas 9101 e 9102
    cd backend
    uv run python loadtest/loadtest.py --steps 1000,2000,4000,8000 --step-s 30

Modelo aberto: os envios saem no horário, sem esperar as respostas anteriores. Um gerador que
espera a resposta antes de mandar a próxima diminui o ritmo justo quando o sistema engasga, e
esconde a saturação (coordinated omission, capítulo 21 do guia).

O gerador não pode ser o gargalo. Montar spans em protobuf custa caro em Python, então ele monta
um lote-modelo por segundo, com o horário de agora, e a cada envio só troca, no lote já
serializado, os 8 bytes que tornam únicos os ids dos traces.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

PROJECT = "Teste de carga"
ENVIRONMENT = "carga"
MARK = b"\xc4\x7a\x9e\x11"  # 4 bytes raros: no lote-modelo, logo depois deles vem o "sal" de cada trace id
TRACES_PER_BATCH = 25

# Um trace como os da loja: o gateway chama o orders, que chama o inventory e o payments, que
# chama um banco externo. Cada chamada tem o lado CLIENT e o SERVER, para o mapa parear.
# (serviço, tipo, índice do pai, método, rota ou serviço chamado, início em ms, duração em ms)
SHAPE: list[tuple[str, int, int | None, str, str, int, int]] = [
    ("carga-gateway", Span.SPAN_KIND_SERVER, None, "POST", "/checkout", 0, 120),
    ("carga-gateway", Span.SPAN_KIND_CLIENT, 0, "POST", "carga-orders", 2, 110),
    ("carga-orders", Span.SPAN_KIND_SERVER, 1, "POST", "/orders", 3, 105),
    ("carga-orders", Span.SPAN_KIND_CLIENT, 2, "GET", "carga-inventory", 5, 20),
    ("carga-inventory", Span.SPAN_KIND_SERVER, 3, "GET", "/stock/{sku}", 6, 15),
    ("carga-orders", Span.SPAN_KIND_CLIENT, 2, "POST", "carga-payments", 30, 70),
    ("carga-payments", Span.SPAN_KIND_SERVER, 5, "POST", "/charge", 31, 65),
    ("carga-payments", Span.SPAN_KIND_CLIENT, 6, "POST", "carga-bank", 35, 50),
]
SPANS_PER_BATCH = TRACES_PER_BATCH * len(SHAPE)


def attr(key: str, value: str | int) -> KeyValue:
    if isinstance(value, int):
        return KeyValue(key=key, value=AnyValue(int_value=value))
    return KeyValue(key=key, value=AnyValue(string_value=value))


def build_template(now_ns: int) -> tuple[bytes, list[int]]:
    """Um lote com TRACES_PER_BATCH traces e onde trocar o sal de cada trace id."""
    scopes: dict[str, ScopeSpans] = {}
    for t in range(TRACES_PER_BATCH):
        trace_id = MARK + bytes(8) + t.to_bytes(4, "big")  # marca + sal (trocado a cada envio) + índice
        span_ids = [(t * len(SHAPE) + i + 1).to_bytes(8, "big") for i in range(len(SHAPE))]
        for i, (service, kind, parent, method, target, start_ms, duration_ms) in enumerate(SHAPE):
            start = now_ns - 200_000_000 + start_ms * 1_000_000  # traces que acabaram de terminar
            server = kind == Span.SPAN_KIND_SERVER
            attributes = [attr("http.request.method", method), attr("http.response.status_code", 200)]
            if server:
                attributes.append(attr("http.route", target))
            else:
                attributes += [attr("server.address", target), attr("server.port", 8000)]
            scopes.setdefault(service, ScopeSpans()).spans.append(
                Span(
                    trace_id=trace_id,
                    span_id=span_ids[i],
                    parent_span_id=span_ids[parent] if parent is not None else b"",
                    name=f"{method} {target}" if server else method,
                    kind=kind,  # type: ignore[arg-type]
                    start_time_unix_nano=start,
                    end_time_unix_nano=start + duration_ms * 1_000_000,
                    attributes=attributes,
                )
            )
    request = ExportTraceServiceRequest()
    for service, scope in scopes.items():
        resource = Resource(
            attributes=[attr("service.name", service), attr("deployment.environment.name", ENVIRONMENT)]
        )
        request.resource_spans.append(ResourceSpans(resource=resource, scope_spans=[scope]))
    payload = request.SerializeToString()
    offsets = []
    at = payload.find(MARK)
    while at != -1:
        offsets.append(at + len(MARK))
        at = payload.find(MARK, at + 1)
    if len(offsets) != SPANS_PER_BATCH:  # a marca apareceu por acaso noutro campo: outro horário resolve
        return build_template(now_ns + 1)
    return payload, offsets


def stamp(template: bytes, offsets: list[int], salt: int) -> bytes:
    body = bytearray(template)
    value = salt.to_bytes(8, "big")
    for offset in offsets:
        body[offset : offset + 8] = value
    return bytes(body)


@dataclass
class StepResult:
    target_spans_s: int
    seconds: float = 0
    sent_batches: int = 0
    accepted_batches: int = 0
    backpressure_batches: int = 0  # recusas 503 (fila cheia): o freio funcionando
    sent_spans_s: float = 0
    accepted_spans_s: float = 0
    backpressure_pct: float = 0
    failed: int = 0  # outros erros e exceções
    ingest_p50_ms: float = 0
    ingest_p99_ms: float = 0
    written_spans_s: float = 0
    max_backlog_batches: int = 0
    max_queue_age_s: float = 0  # a idade do lote mais antigo: acima de 30 s, a ingestão freia
    lag_p95_s: float | None = None
    max_in_flight: int = 0
    generator_delay_ms: float = 0  # o quanto o próprio gerador atrasou: se cresce, o degrau não vale
    latencies_ms: list[float] = field(default_factory=list, repr=False)


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


class Metrics:
    """Lê o /metrics da ingestão e do processador."""

    def __init__(self, client: httpx.AsyncClient, ingest_url: str, processor_url: str) -> None:
        self.client = client
        self.ingest_url = ingest_url
        self.processor_url = processor_url

    async def read(self, url: str) -> dict[str, float]:
        samples: dict[str, float] = {}
        text = (await self.client.get(url, timeout=5)).text
        for line in text.splitlines():
            if line and not line.startswith("#"):
                name, _, value = line.rpartition(" ")
                samples[name] = float(value)
        return samples

    async def snapshot(self) -> dict[str, float]:
        return {**await self.read(self.ingest_url), **await self.read(self.processor_url)}


def lag_p95(before: dict[str, float], after: dict[str, float]) -> float | None:
    """O p95 do atraso até o banco só no intervalo, pelas diferenças dos buckets do histograma."""
    prefix = 'traceflow_processor_lag_seconds_bucket{le="'
    buckets = sorted(
        (float(name[len(prefix) : -2]), after[name] - before.get(name, 0))
        for name in after
        if name.startswith(prefix)
    )
    total = buckets[-1][1] if buckets else 0
    if total <= 0:
        return None
    lower, below = 0.0, 0.0
    for bound, count in buckets:
        if count >= 0.95 * total:
            if math.isinf(bound):
                return lower  # passou do maior bucket: só se sabe que é maior que ele
            return lower + (bound - lower) * (0.95 * total - below) / max(count - below, 1e-9)
        lower, below = bound, count
    return None


async def send(
    client: httpx.AsyncClient, url: str, key: str, body: bytes, step: StepResult, scheduled_at: float
) -> None:
    """O tempo conta do horário em que o lote deveria sair, e não de quando saiu: se ele esperou
    uma conexão livre no próprio cliente, essa espera também é atraso que o sistema causou."""
    loop = asyncio.get_running_loop()
    try:
        response = await client.post(
            url,
            content=body,
            headers={"content-type": "application/x-protobuf", "authorization": f"Bearer {key}"},
        )
    except httpx.HTTPError:
        step.failed += 1
        return
    step.latencies_ms.append((loop.time() - scheduled_at) * 1000)
    if response.status_code == 200:
        step.accepted_batches += 1
    elif response.status_code == 503:
        step.backpressure_batches += 1
    else:
        step.failed += 1


async def run_step(
    client: httpx.AsyncClient,
    metrics: Metrics,
    url: str,
    key: str,
    rate: int,
    seconds: float,
    salt: list[int],
) -> StepResult:
    step = StepResult(target_spans_s=rate)
    interval = SPANS_PER_BATCH / rate
    loop = asyncio.get_running_loop()
    before = await metrics.snapshot()
    template, offsets = build_template(time.time_ns())
    built_at = loop.time()
    in_flight: set[asyncio.Task[None]] = set()
    start = next_at = loop.time()
    last_poll = start
    polls: list[asyncio.Task[None]] = []

    async def poll_backlog() -> None:
        samples = await metrics.read(metrics.ingest_url)
        step.max_backlog_batches = max(
            step.max_backlog_batches, int(samples["traceflow_ingest_backlog_batches"])
        )
        step.max_queue_age_s = max(
            step.max_queue_age_s, round(samples["traceflow_ingest_queue_age_seconds"], 1)
        )

    while (now := loop.time()) < start + seconds:
        if now - built_at >= 1:
            template, offsets = build_template(time.time_ns())
            built_at = now
        if now - last_poll >= 1:
            last_poll = now
            polls.append(asyncio.create_task(poll_backlog()))
        if next_at > now:
            await asyncio.sleep(next_at - now)
        salt[0] += 1
        step.generator_delay_ms = max(step.generator_delay_ms, round((loop.time() - next_at) * 1000, 1))
        body = stamp(template, offsets, salt[0])
        task = asyncio.create_task(send(client, url, key, body, step, scheduled_at=next_at))
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)
        step.max_in_flight = max(step.max_in_flight, len(in_flight))
        step.sent_batches += 1
        next_at += interval  # no horário marcado, mesmo que a resposta anterior não tenha chegado
    elapsed = loop.time() - start
    await asyncio.gather(*in_flight, *polls)
    after = await metrics.snapshot()

    step.seconds = round(elapsed, 1)
    step.sent_spans_s = round(step.sent_batches * SPANS_PER_BATCH / elapsed)
    step.accepted_spans_s = round(step.accepted_batches * SPANS_PER_BATCH / elapsed)
    step.backpressure_pct = round(100 * step.backpressure_batches / max(step.sent_batches, 1), 1)
    step.ingest_p50_ms = round(quantile(step.latencies_ms, 0.50), 1)
    step.ingest_p99_ms = round(quantile(step.latencies_ms, 0.99), 1)
    written = (
        after["traceflow_processor_spans_written_total"] - before["traceflow_processor_spans_written_total"]
    )
    step.written_spans_s = round(written / elapsed)
    p95 = lag_p95(before, after)
    step.lag_p95_s = round(p95, 3) if p95 is not None else None
    return step


async def ensure_key(api_url: str) -> str:
    """Uma conta e um projeto só para a carga, e uma chave nova a cada rodada."""
    async with httpx.AsyncClient(base_url=api_url, timeout=10) as api:
        account = {
            "email": "carga@traceflow.dev",
            "password": "teste-de-carga-local",
            "name": "Teste de carga",
        }
        if (await api.post("/api/auth/register", json=account)).status_code != 201:
            response = await api.post("/api/auth/login", json={k: account[k] for k in ("email", "password")})
            response.raise_for_status()
        projects = (await api.get("/api/projects")).json()
        project = next((p for p in projects if p["name"] == PROJECT), None)
        if project is None:
            project = (await api.post("/api/projects", json={"name": PROJECT})).json()
        created = await api.post(
            f"/api/projects/{project['id']}/keys", json={"name": f"carga {time.strftime('%H:%M:%S')}"}
        )
        created.raise_for_status()
        print(f"projeto {project['id']} ({PROJECT}), chave {created.json()['prefix']}…")
        return str(created.json()["key"])


async def wait_drained(metrics: Metrics, limit_s: float) -> float:
    """Depois do último degrau: quanto tempo a fila leva para esvaziar."""
    started = time.monotonic()
    while time.monotonic() - started < limit_s:
        samples = await metrics.read(metrics.ingest_url)
        if samples["traceflow_ingest_backlog_batches"] == 0:
            return round(time.monotonic() - started, 1)
        await asyncio.sleep(0.5)
    return math.inf


async def main(args: argparse.Namespace) -> tuple[list[StepResult], float]:
    key = await ensure_key(args.api)
    await asyncio.sleep(1)
    limits = httpx.Limits(max_connections=args.connections, max_keepalive_connections=args.connections)
    async with httpx.AsyncClient(limits=limits, timeout=30) as client:
        metrics = Metrics(client, args.ingest_metrics, args.processor_metrics)
        salt = [time.time_ns()]  # um ponto de partida novo por rodada: os traces nunca se repetem
        results: list[StepResult] = []
        header = (
            f"{'alvo':>7} {'enviado':>8} {'aceito':>8} {'503':>6} {'p50 ms':>7} {'p99 ms':>7} "
            f"{'gravado':>8} {'fila máx':>9} {'idade máx':>10} {'atraso p95':>11}"
        )
        print(header)
        for rate in args.steps:
            step = await run_step(client, metrics, args.ingest, key, rate, args.step_s, salt)
            results.append(step)
            lag = f"{step.lag_p95_s:.2f} s" if step.lag_p95_s is not None else "-"
            print(
                f"{rate:>7} {step.sent_spans_s:>8} {step.accepted_spans_s:>8} {step.backpressure_pct:>5}% "
                f"{step.ingest_p50_ms:>7} {step.ingest_p99_ms:>7} {step.written_spans_s:>8} "
                f"{step.max_backlog_batches:>9} {step.max_queue_age_s:>8} s {lag:>11}"
                + (f"  ({step.failed} erros)" if step.failed else "")
                + (
                    f"  [gerador atrasou {step.generator_delay_ms} ms]"
                    if step.generator_delay_ms > 100
                    else ""
                )
            )
        drained = await wait_drained(metrics, args.drain_s)
        print(f"a fila esvaziou {drained} s depois do último degrau")
    return results, drained


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--steps", type=lambda s: [int(x) for x in s.split(",")], default=[1000, 2000, 4000, 8000]
    )
    parser.add_argument("--step-s", type=float, default=30, help="duração de cada degrau")
    parser.add_argument("--ingest", default="http://localhost:4318/v1/traces")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--ingest-metrics", default="http://localhost:9101/metrics")
    parser.add_argument("--processor-metrics", default="http://localhost:9102/metrics")
    parser.add_argument("--connections", type=int, default=64)
    parser.add_argument("--drain-s", type=float, default=300)
    parser.add_argument("--out", help="grava o resultado em JSON")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    steps, drained_s = asyncio.run(main(arguments))
    if arguments.out:
        report = {
            "spans_per_batch": SPANS_PER_BATCH,
            "drained_s": drained_s,
            "steps": [{k: v for k, v in asdict(s).items() if k != "latencies_ms"} for s in steps],
        }
        Path(arguments.out).write_text(json.dumps(report, indent=2), encoding="utf-8")

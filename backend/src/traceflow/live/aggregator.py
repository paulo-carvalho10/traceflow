"""As métricas ao vivo: RED por serviço, em baldes de 1 segundo, pelo tempo do evento (D8).

Cada span SERVER cai no balde do segundo em que TERMINOU, não do segundo em que chegou: os
exportadores mandam em lotes, e contar pela chegada faria a taxa oscilar com o ritmo dos
lotes. Os baldes ficam guardados por 60 s numa "roda" (o segundo s usa a posição s % 60).

O retrato (snapshot) de cada segundo cobre a janela de 10 s que termina 3 s atrás: o segundo
atual ainda está incompleto (lotes a caminho), e mostrá-lo faria a taxa "cair" no fim do
gráfico. Esses 3 s funcionam como a marca d'água dos sistemas de streaming.

Além de cada serviço, o projeto tem a linha "entrada": as requisições que ENTRARAM no
sistema (spans raiz). Somar os serviços contaria uma compra várias vezes (gateway, orders,
payments...); a entrada conta cada requisição de cliente uma vez só.

As LIGAÇÕES do mapa (Etapa 7) vêm dos spans CLIENT, do lado de quem chama (D9): é quem chama
que sente a falha, mesmo quando o chamado caiu e não manda mais nada. Elas ficam guardadas
pelo endereço chamado; o nome do serviço por trás dele vem do catálogo de endereços
(topology.py) na hora de montar o retrato.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from traceflow.live.histogram import Histogram
from traceflow.normalize import SpanRow

RING_SECONDS = 60
WINDOW_SECONDS = 10
WATERMARK_SECONDS = 3
ENTRY = "__entrada__"  # a linha do projeto: só as requisições que entraram (spans raiz)
# "Sem resposta": as chamadas para um serviço conhecido falham e ele não atende nada. Com
# menos de 5 chamadas na janela, o sinal é fraco demais para afirmar isso.
NO_RESPONSE_MIN_CALLS = 5

Resolver = Callable[[int, str, str], str | None]  # (projeto, ambiente, endereço) -> serviço


def call_failed(row: SpanRow) -> bool:
    """Uma chamada falhou se a resposta foi 5xx ou se nem houve resposta (D49).

    O OpenTelemetry marca como erro, no span CLIENT, também as respostas 4xx. Mas um 402
    (cartão recusado) ou um 404 (produto inexistente) são respostas legítimas do serviço
    chamado: contá-los como falha deixaria a loja saudável com ~1,5% de "falha" no mapa e
    a ligação payments → bank "doente" por causa de cartões recusados. É o mesmo critério
    do RED dos serviços: falha do sistema, não do pedido.
    """
    if row.http_status_code is not None:
        return row.http_status_code >= 500
    return row.status == "error"  # sem código: conexão recusada, tempo esgotado...


@dataclass
class SecondBucket:
    second: int = -1
    requests: int = 0
    errors: int = 0
    roots: int = 0  # quantas dessas requisições ENTRARAM no sistema por aqui (spans raiz)
    histogram: Histogram = field(default_factory=Histogram)

    def reset(self, second: int) -> None:
        self.second = second
        self.requests = 0
        self.errors = 0
        self.roots = 0
        self.histogram = Histogram()


Key = tuple[int, str, str]  # (projeto, ambiente, serviço)
EdgeKey = tuple[int, str, str, str]  # (projeto, ambiente, quem chama, endereço chamado)
Ring = list[SecondBucket]


@dataclass
class _Window:
    requests: int = 0
    errors: int = 0
    roots: int = 0
    histogram: Histogram = field(default_factory=Histogram)


class LiveAggregator:
    def __init__(self) -> None:
        self._rings: dict[Key, Ring] = {}
        self._edges: dict[EdgeKey, Ring] = {}
        self.late = 0  # spans que chegaram depois de o segundo deles sair da roda

    def add(self, rows: Iterable[SpanRow], now: float) -> None:
        oldest = int(now) - RING_SECONDS + 1
        for row in rows:
            if row.kind not in ("server", "client"):
                continue
            ended = int(row.start_time.timestamp() + row.duration_ms / 1000)
            if ended < oldest:
                self.late += 1
                continue
            if row.kind == "client":
                # a ligação do mapa: conta do lado de quem chama, pelo endereço chamado
                if row.peer_address:
                    edge = (row.project_id, row.environment, row.service, row.peer_address)
                    _count(self._edges, edge, ended, row.duration_ms, call_failed(row), root=False)
                continue
            # o RED de um serviço é o que ele ATENDEU (spans SERVER)
            failed = row.status == "error"
            root = row.parent_span_id is None
            service = (row.project_id, row.environment, row.service)
            _count(self._rings, service, ended, row.duration_ms, failed, root)
            if root:
                entry = (row.project_id, row.environment, ENTRY)
                _count(self._rings, entry, ended, row.duration_ms, failed, root)

    def snapshots(self, now: float, resolve: Resolver | None = None) -> dict[tuple[int, str], dict[str, Any]]:
        """Um retrato por (projeto, ambiente) com atividade no último minuto."""
        window_end = int(now) - WATERMARK_SECONDS  # exclusivo
        window_start = window_end - WINDOW_SECONDS
        series_start = window_end - RING_SECONDS + WATERMARK_SECONDS
        grouped: dict[tuple[int, str], dict[str, Any]] = {}

        def snapshot_of(project: int, environment: str) -> dict[str, Any]:
            return grouped.setdefault(
                (project, environment),
                {
                    "project_id": project,
                    "environment": environment,
                    "generated_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
                    "window": {"from": window_start, "to": window_end, "seconds": WINDOW_SECONDS},
                    "entry": None,
                    "services": [],
                    "edges": [],
                    "unresponsive": [],
                },
            )

        for key in list(self._rings):
            ring = self._rings[key]
            if all(b.second < series_start for b in ring):
                del self._rings[key]  # sem nada no último minuto: some do retrato e libera memória
                continue
            project, environment, service = key
            by_second = {b.second: b for b in ring if series_start <= b.second < window_end}
            window = _window(by_second, window_start, window_end)
            stats = {
                **_red(window),
                "entry_rps": window.roots / WINDOW_SECONDS,
                "series": _series(by_second, series_start, window_end),
            }
            snap = snapshot_of(project, environment)
            if service == ENTRY:
                snap["entry"] = stats
            else:
                snap["services"].append({"name": service, **stats})

        # As ligações: quem chama, o endereço e, se o catálogo já sabe, o serviço por trás dele
        incoming: dict[Key, _Window] = {}  # o que chegou em cada serviço conhecido, pelas ligações
        for edge_key in list(self._edges):
            ring = self._edges[edge_key]
            if all(b.second < series_start for b in ring):
                del self._edges[edge_key]
                continue
            project, environment, caller, address = edge_key
            by_second = {b.second: b for b in ring if series_start <= b.second < window_end}
            window = _window(by_second, window_start, window_end)
            target = resolve(project, environment, address) if resolve else None
            snapshot_of(project, environment)["edges"].append(
                {
                    "source": caller,
                    "target": target or address,
                    "address": address,
                    "virtual": target is None,  # ninguém atendeu com um span: API externa, sem instrumentação
                    "rps": window.requests / WINDOW_SECONDS,
                    "error_rate": window.errors / window.requests if window.requests else 0.0,
                    "p50_ms": window.histogram.quantile(0.50),
                    "p95_ms": window.histogram.quantile(0.95),
                    "requests": window.requests,
                }
            )
            if target is not None:
                total = incoming.setdefault((project, environment, target), _Window())
                total.requests += window.requests
                total.errors += window.errors

        # "Sem resposta": chamam o serviço, as chamadas falham, e ele não atende nada (nem um
        # span SERVER na janela). É o que acontece quando ele cai: some dos spans, mas quem
        # depende dele continua tentando, e o nome dele já foi aprendido.
        for (project, environment, service), calls in incoming.items():
            snap = grouped[(project, environment)]
            served = next((s["requests"] for s in snap["services"] if s["name"] == service), 0)
            if calls.requests >= NO_RESPONSE_MIN_CALLS and served == 0 and calls.errors * 2 >= calls.requests:
                snap["unresponsive"].append(service)

        for snap in grouped.values():
            snap["services"].sort(key=lambda s: s["name"])
            snap["edges"].sort(key=lambda e: (e["source"], e["target"]))
            snap["unresponsive"].sort()
        return grouped


def _count(
    rings: dict[Any, Ring], key: Any, second: int, duration_ms: float, failed: bool, root: bool
) -> None:
    ring = rings.get(key)
    if ring is None:
        ring = rings[key] = [SecondBucket() for _ in range(RING_SECONDS)]
    bucket = ring[second % RING_SECONDS]
    if bucket.second != second:
        bucket.reset(second)  # a posição guardava um segundo de 60 s atrás: recomeça
    bucket.requests += 1
    bucket.errors += failed
    bucket.roots += root
    bucket.histogram.add(duration_ms)


def _window(by_second: dict[int, SecondBucket], start: int, end: int) -> _Window:
    window = _Window()
    for second in range(start, end):
        bucket = by_second.get(second)
        if bucket:
            window.requests += bucket.requests
            window.errors += bucket.errors
            window.roots += bucket.roots
            window.histogram.merge(bucket.histogram)
    return window


def _red(window: _Window) -> dict[str, Any]:
    requests, errors = window.requests, window.errors
    return {
        "rps": requests / WINDOW_SECONDS,
        "error_rate": errors / requests if requests else 0.0,
        "availability": 1 - errors / requests if requests else None,
        "p50_ms": window.histogram.quantile(0.50),
        "p95_ms": window.histogram.quantile(0.95),
        "p99_ms": window.histogram.quantile(0.99),
        "requests": requests,
    }


def _series(by_second: dict[int, SecondBucket], start: int, end: int) -> list[dict[str, Any]]:
    # O p95 de cada ponto usa os 10 s anteriores (janela móvel), como o número em destaque:
    # o p95 de um segundo só, com ~20 requisições, saltava entre baldes vizinhos e desenhava
    # um serrote que não existe no sistema. A janela DESLIZA: soma o segundo que entra e
    # subtrai o que sai, em vez de somar 10 histogramas para cada ponto (de 12 para 3,7 ms
    # por retrato com a loja; capítulo 26 do guia).
    series = []
    rolling = Histogram()
    for second in range(start, end):
        bucket = by_second.get(second)
        if bucket is not None:
            rolling.merge(bucket.histogram)
        if (leaving := by_second.get(second - WINDOW_SECONDS)) is not None:
            rolling.subtract(leaving.histogram)
        series.append(
            {
                "t": second,
                "rps": bucket.requests if bucket else 0,
                "errors": bucket.errors if bucket else 0,
                "p95_ms": rolling.quantile(0.95),
            }
        )
    return series

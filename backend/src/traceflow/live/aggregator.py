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
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from traceflow.live.histogram import Histogram
from traceflow.normalize import SpanRow

RING_SECONDS = 60
WINDOW_SECONDS = 10
WATERMARK_SECONDS = 3
ENTRY = "__entrada__"  # a linha do projeto: só as requisições que entraram (spans raiz)


@dataclass
class SecondBucket:
    second: int = -1
    requests: int = 0
    errors: int = 0
    histogram: Histogram = field(default_factory=Histogram)

    def reset(self, second: int) -> None:
        self.second = second
        self.requests = 0
        self.errors = 0
        self.histogram = Histogram()


Key = tuple[int, str, str]  # (projeto, ambiente, serviço)


class LiveAggregator:
    def __init__(self) -> None:
        self._rings: dict[Key, list[SecondBucket]] = {}
        self.late = 0  # spans que chegaram depois de o segundo deles sair da roda

    def add(self, rows: Iterable[SpanRow], now: float) -> None:
        oldest = int(now) - RING_SECONDS + 1
        for row in rows:
            if row.kind != "server":
                # o RED de um serviço é o que ele ATENDEU; as chamadas que ele fez são das arestas (Etapa 7)
                continue
            ended = int(row.start_time.timestamp() + row.duration_ms / 1000)
            if ended < oldest:
                self.late += 1
                continue
            failed = row.status == "error"
            self._count((row.project_id, row.environment, row.service), ended, row.duration_ms, failed)
            if row.parent_span_id is None:
                self._count((row.project_id, row.environment, ENTRY), ended, row.duration_ms, failed)

    def _count(self, key: Key, second: int, duration_ms: float, failed: bool) -> None:
        ring = self._rings.get(key)
        if ring is None:
            ring = self._rings[key] = [SecondBucket() for _ in range(RING_SECONDS)]
        bucket = ring[second % RING_SECONDS]
        if bucket.second != second:
            bucket.reset(second)  # a posição guardava um segundo de 60 s atrás: recomeça
        bucket.requests += 1
        bucket.errors += failed
        bucket.histogram.add(duration_ms)

    def snapshots(self, now: float) -> dict[tuple[int, str], dict[str, Any]]:
        """Um retrato por (projeto, ambiente) com atividade no último minuto."""
        window_end = int(now) - WATERMARK_SECONDS  # exclusivo
        window_start = window_end - WINDOW_SECONDS
        series_start = window_end - RING_SECONDS + WATERMARK_SECONDS
        grouped: dict[tuple[int, str], dict[str, Any]] = {}

        for key in list(self._rings):
            ring = self._rings[key]
            if all(b.second < series_start for b in ring):
                del self._rings[key]  # sem nada no último minuto: some do retrato e libera memória
                continue
            project, environment, service = key
            by_second = {b.second: b for b in ring if series_start <= b.second < window_end}
            window = Histogram()
            requests = errors = 0
            for second in range(window_start, window_end):
                bucket = by_second.get(second)
                if bucket:
                    requests += bucket.requests
                    errors += bucket.errors
                    window.merge(bucket.histogram)
            series = []
            # O p95 de cada ponto usa os 10 s anteriores (janela móvel), como o número em
            # destaque: o p95 de um segundo só, com ~20 requisições, saltava entre baldes
            # vizinhos e desenhava um serrote que não existe no sistema. A janela DESLIZA:
            # soma o segundo que entra e subtrai o que sai, em vez de somar 10 histogramas
            # para cada ponto (de 12 para 3,7 ms por retrato com a loja; capítulo 26 do guia).
            rolling = Histogram()
            for second in range(series_start, window_end):
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
            stats = {
                "rps": requests / WINDOW_SECONDS,
                "error_rate": errors / requests if requests else 0.0,
                "availability": 1 - errors / requests if requests else None,
                "p50_ms": window.quantile(0.50),
                "p95_ms": window.quantile(0.95),
                "p99_ms": window.quantile(0.99),
                "requests": requests,
                "series": series,
            }
            snap = grouped.setdefault(
                (project, environment),
                {
                    "project_id": project,
                    "environment": environment,
                    "generated_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
                    "window": {"from": window_start, "to": window_end, "seconds": WINDOW_SECONDS},
                    "entry": None,
                    "services": [],
                },
            )
            if service == ENTRY:
                snap["entry"] = stats
            else:
                snap["services"].append({"name": service, **stats})

        for snap in grouped.values():
            snap["services"].sort(key=lambda s: s["name"])
        return grouped

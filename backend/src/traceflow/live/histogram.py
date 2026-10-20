"""Histograma de baldes exponenciais: percentis com memória fixa (capítulo 6 do guia).

Cada balde é 20% maior que o anterior, de 0,1 ms a 60 s: 73 baldes. Um valor cai no balde
cuja faixa o contém; o percentil é estimado pelo meio (geométrico) do balde onde a contagem
acumulada passa da fração pedida. O erro relativo fica abaixo de 10%
(raiz de 1,2, menos 1: cerca de 9,5%).

A propriedade que importa: histogramas se SOMAM. Dez histogramas de 1 s viram o de 10 s
sem perder nada, coisa impossível com percentis prontos (média de p95 não é p95).
"""

from __future__ import annotations

import math
from collections.abc import Iterable

MIN_MS = 0.1
FACTOR = 1.2
MAX_MS = 60_000.0
BUCKETS = math.ceil(math.log(MAX_MS / MIN_MS) / math.log(FACTOR))  # 73
_LOG_FACTOR = math.log(FACTOR)


def bucket_of(duration_ms: float) -> int:
    """Em que balde cai uma duração. Abaixo de 0,1 ms vai no primeiro; acima de 60 s, no último."""
    if duration_ms <= MIN_MS:
        return 0
    return min(BUCKETS - 1, int(math.log(duration_ms / MIN_MS) / _LOG_FACTOR))


def bucket_value(index: int) -> float:
    """O valor que representa o balde: o meio geométrico da faixa [0,1·1,2ⁱ, 0,1·1,2ⁱ⁺¹)."""
    return float(MIN_MS * FACTOR ** (index + 0.5))


class Histogram:
    __slots__ = ("counts", "total")

    def __init__(self) -> None:
        self.counts = [0] * BUCKETS
        self.total = 0

    def add(self, duration_ms: float) -> None:
        self.counts[bucket_of(duration_ms)] += 1
        self.total += 1

    def merge(self, other: Histogram) -> None:
        """Soma outro histograma a este, balde a balde."""
        for i, c in enumerate(other.counts):
            if c:
                self.counts[i] += c
        self.total += other.total

    def subtract(self, other: Histogram) -> None:
        """Tira de volta um histograma que foi somado antes (a janela deslizante)."""
        for i, c in enumerate(other.counts):
            if c:
                self.counts[i] -= c
        self.total -= other.total

    def quantile(self, q: float) -> float | None:
        """O valor abaixo do qual está a fração q das medições (q=0,95 é o p95). None se vazio."""
        if self.total == 0:
            return None
        target = q * self.total
        seen = 0
        for i, c in enumerate(self.counts):
            seen += c
            if seen >= target and c:
                return bucket_value(i)
        return bucket_value(BUCKETS - 1)

    @classmethod
    def of(cls, values: Iterable[float]) -> Histogram:
        h = cls()
        for v in values:
            h.add(v)
        return h

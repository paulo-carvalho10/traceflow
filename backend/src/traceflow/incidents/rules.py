"""As regras de detecção: "se a métrica de um serviço passar do limite, ele fica neste estado".

Cada projeto tem as suas (tabela alert_rules), editáveis pelo dono. Um projeto nasce com as
regras padrão abaixo. "Sem resposta" não é regra: é um fato observado no mapa (D51).

Uma regra é avaliada sobre os números do retrato (a janela de 10 s) e só vale com tráfego
suficiente (min_requests): com 3 requisições, 1 erro são 33%, e isso não diz nada.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Metric = Literal["error_rate", "p95_ms", "p99_ms", "rps", "availability"]
State = Literal["healthy", "degraded", "failing", "unresponsive"]

SEVERITY_OF_STATE: dict[State, int] = {"healthy": 0, "degraded": 1, "failing": 2, "unresponsive": 3}
# Numa regra relativa ("p95 >= 2x a linha de base"), o aumento também precisa passar de 50 ms:
# um serviço de 4 ms que vai a 9 ms dobrou, mas ninguém sente.
RELATIVE_MIN_DELTA_MS = 50.0


@dataclass(frozen=True)
class Rule:
    target: str  # um serviço, ou "*" para todos
    metric: Metric
    operator: Literal[">=", "<="]
    threshold: float
    state: Literal["degraded", "failing"]
    relative: bool = False  # threshold vezes a linha de base (só latência)
    min_requests: int = 20
    id: int | None = None


DEFAULT_RULES = (
    Rule("*", "error_rate", ">=", 0.05, "degraded"),
    Rule("*", "p95_ms", ">=", 2.0, "degraded", relative=True),
    Rule("*", "error_rate", ">=", 0.25, "failing"),
)


@dataclass(frozen=True)
class NodeStats:
    requests: int
    error_rate: float
    p95_ms: float | None
    p99_ms: float | None
    rps: float

    @property
    def availability(self) -> float:
        return 1 - self.error_rate


@dataclass(frozen=True)
class Verdict:
    """O que as regras dizem de um nó agora, e por quê (para mostrar na tela)."""

    state: State
    rule: Rule | None = None
    value: float | None = None  # o valor medido que disparou a regra
    baseline: float | None = None  # a linha de base, nas regras relativas
    by_callers: bool = False  # medido nas chamadas que chegam nele, e não no que ele mesmo registrou


HEALTHY = Verdict("healthy")


def evaluate(service: str, stats: NodeStats, rules: Iterable[Rule], baseline: float | None) -> Verdict:
    """O pior estado entre as regras que disparam para este serviço."""
    worst = HEALTHY
    for rule in rules:
        if rule.target not in ("*", service) or stats.requests < rule.min_requests:
            continue
        value = getattr(stats, rule.metric)
        if value is None:
            continue
        if rule.relative:
            if baseline is None:  # ainda aprendendo o normal deste serviço: a regra espera
                continue
            limit = rule.threshold * baseline
            fired = value >= limit and value - baseline >= RELATIVE_MIN_DELTA_MS
        else:
            fired = value >= rule.threshold if rule.operator == ">=" else value <= rule.threshold
        if fired and SEVERITY_OF_STATE[rule.state] > SEVERITY_OF_STATE[worst.state]:
            worst = Verdict(rule.state, rule, value, baseline if rule.relative else None)
    return worst

"""Os textos dos incidentes, em português: o motivo de cada estado e as frases da linha do tempo.

Ficam no backend porque a linha do tempo é gravada: o texto de um evento é o que se disse na
hora, mesmo que a regra mude depois. Os números vão junto, em "data", para a tela usar.
"""

from __future__ import annotations

from traceflow.incidents.rules import State, Verdict

STATE_LABEL: dict[State, str] = {
    "healthy": "saudável",
    "degraded": "degradado",
    "failing": "falhando",
    "unresponsive": "sem resposta",
}
METRIC_LABEL = {
    "error_rate": "erro",
    "p95_ms": "p95",
    "p99_ms": "p99",
    "rps": "tráfego",
    "availability": "disponibilidade",
}


def pct(fraction: float) -> str:
    text = f"{fraction * 100:.1f}".rstrip("0").rstrip(".")
    return f"{text.replace('.', ',')}%"


def duration(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.1f}".replace(".", ",") + " s"
    return f"{ms:.0f} ms"


def metric_value(metric: str, value: float) -> str:
    if metric in ("error_rate", "availability"):
        return pct(value)
    if metric == "rps":
        return f"{value:.1f}/s".replace(".", ",")
    return duration(value)


def reason(verdict: Verdict) -> str:
    """Por que o nó está neste estado, numa frase curta."""
    if verdict.state == "unresponsive":
        return "as chamadas para ele falham e ele não atende nada"
    rule, value = verdict.rule, verdict.value
    if rule is None or value is None:
        return STATE_LABEL[verdict.state]
    label = METRIC_LABEL[rule.metric]
    if rule.relative and verdict.baseline:
        times = f"{value / verdict.baseline:.1f}".replace(".", ",")
        base = duration(verdict.baseline)
        return f"{label} {duration(value)}, {times}× a linha de base ({base})"  # noqa: RUF001 (o sinal de vezes)
    operator = "≥" if rule.operator == ">=" else "≤"
    limit = metric_value(rule.metric, rule.threshold)
    where = " nas chamadas que chegam nele" if verdict.by_callers else ""
    return f"{label} {metric_value(rule.metric, value)}{where} (regra: {label} {operator} {limit})"


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " e " + names[-1]

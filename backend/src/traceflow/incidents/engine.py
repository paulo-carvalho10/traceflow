"""O motor de saúde: a cada segundo, transforma o retrato em estados, causa, impacto e severidade.

Mantém a memória que as funções puras não têm: o estado em vigor de cada nó (histerese) e as
linhas de base (do p95 de cada nó e de cada rota de entrada).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from traceflow.incidents.analysis import Analysis, Call, Endpoint, Node, analyze
from traceflow.incidents.health import Baseline, NodeHealth
from traceflow.incidents.rules import HEALTHY, SEVERITY_OF_STATE, NodeStats, Rule, State, Verdict, evaluate

# Do lado de quem chama, só as regras de ERRO valem: a latência vista por quem chama inclui a
# rede, e a linha de base de cada serviço foi aprendida do lado dele.
CALLER_SIDE_METRICS = ("error_rate", "availability")

Channel = tuple[int, str]  # (projeto, ambiente)


@dataclass
class Assessment:
    verdicts: dict[str, Verdict]  # o estado em vigor de cada nó visto, com o motivo
    changes: list[tuple[str, State, State]]  # (nó, antes, depois) neste segundo
    analysis: Analysis
    virtual: set[str] = field(default_factory=set)

    @property
    def sick(self) -> bool:
        return any(v.state != "healthy" for v in self.verdicts.values())


class Assessor:
    def __init__(self) -> None:
        self._nodes: dict[Channel, dict[str, NodeHealth]] = {}
        self._routes: dict[Channel, dict[tuple[str, str], Baseline]] = {}

    def assess(
        self, snapshot: dict[str, Any], rules: list[Rule], now: float, *, learn_routes: bool = True
    ) -> Assessment:
        channel = (snapshot["project_id"], snapshot["environment"])
        nodes = self._nodes.setdefault(channel, {})
        stats, virtual = node_stats(snapshot)
        callers = caller_stats(snapshot)
        caller_rules = [r for r in rules if r.metric in CALLER_SIDE_METRICS]
        unresponsive = set(snapshot.get("unresponsive", []))

        changes: list[tuple[str, State, State]] = []
        # inclui quem só aparece nas chamadas que chegam nele: o serviço que caiu não manda span
        for name in sorted(set(stats) | set(callers) | unresponsive | set(nodes)):
            health = nodes.setdefault(name, NodeHealth(since=now))
            s = stats.get(name)
            if name in unresponsive:
                raw = Verdict("unresponsive")
            else:
                own = evaluate(name, s, rules, health.baseline.ready) if s else HEALTHY
                # Quem chama sente a falha (D9): um serviço que caiu atrás de um balanceador não
                # registra erro nenhum, ele só some; quem o chama vê 503 desde o primeiro segundo.
                seen = (
                    evaluate(name, callers[name], caller_rules, None)
                    if name in callers and name not in virtual
                    else HEALTHY
                )
                if SEVERITY_OF_STATE[seen.state] > SEVERITY_OF_STATE[own.state]:
                    raw = Verdict(seen.state, seen.rule, seen.value, by_callers=True)
                else:
                    raw = own
            before = health.state
            if health.observe(raw, now, s.p95_ms if s else None, s.requests if s else 0):
                changes.append((name, before, health.state))

        graph = {
            name: Node(
                name=name,
                state=h.state,
                error_rate=stats[name].error_rate if name in stats else 0.0,
                p95_ms=stats[name].p95_ms if name in stats else None,
                baseline_ms=h.baseline.ready,
                sick_by=_sick_by(h.verdict),
            )
            for name, h in nodes.items()
        }
        calls = [Call(e["source"], e["target"], e["error_rate"]) for e in snapshot.get("edges", [])]
        endpoints = self._endpoints(channel, snapshot, learn=learn_routes)
        return Assessment(
            verdicts={name: h.verdict for name, h in nodes.items()},
            changes=changes,
            analysis=analyze(graph, calls, endpoints),
            virtual=virtual,
        )

    def _endpoints(self, channel: Channel, snapshot: dict[str, Any], *, learn: bool) -> list[Endpoint]:
        baselines = self._routes.setdefault(channel, {})
        result = []
        for e in snapshot.get("entrypoints", []):
            baseline = baselines.setdefault((e["service"], e["route"]), Baseline())
            # a linha de base da rota só aprende fora de incidente, com a rota bem
            if learn and e["p95_ms"] is not None and e["requests"] >= 20 and e["error_rate"] < 0.05:
                baseline.learn(e["p95_ms"])
            result.append(
                Endpoint(
                    route=e["route"],
                    service=e["service"],
                    nodes=frozenset(e["nodes"]),
                    rps=e["rps"],
                    error_rate=e["error_rate"],
                    p95_ms=e["p95_ms"],
                    requests=e["requests"],
                    baseline_ms=baseline.ready,
                )
            )
        return result


def node_stats(snapshot: dict[str, Any]) -> tuple[dict[str, NodeStats], set[str]]:
    """Os números de cada nó: os serviços pelo que atenderam; os externos, pelas chamadas que
    chegaram neles (ninguém os mede por dentro: um nó virtual herda a saúde das ligações)."""
    stats = {
        s["name"]: NodeStats(s["requests"], s["error_rate"], s["p95_ms"], s.get("p99_ms"), s["rps"])
        for s in snapshot.get("services", [])
    }
    incoming: dict[str, list[dict[str, Any]]] = {}
    for e in snapshot.get("edges", []):
        if e["virtual"]:
            incoming.setdefault(e["target"], []).append(e)
    for name, edges in incoming.items():
        requests = sum(e["requests"] for e in edges)
        failures = sum(e["error_rate"] * e["requests"] for e in edges)
        p95s = [e["p95_ms"] for e in edges if e["p95_ms"] is not None]
        stats[name] = NodeStats(
            requests=requests,
            error_rate=failures / requests if requests else 0.0,
            p95_ms=max(p95s) if p95s else None,  # sem os histogramas somados, o maior p95 é o honesto
            p99_ms=None,
            rps=sum(e["rps"] for e in edges),
        )
    return stats, set(incoming)


def caller_stats(snapshot: dict[str, Any]) -> dict[str, NodeStats]:
    """Cada serviço visto por quem o chama: as ligações que chegam nele, somadas (só erro e volume)."""
    incoming: dict[str, list[dict[str, Any]]] = {}
    for e in snapshot.get("edges", []):
        if not e["virtual"]:
            incoming.setdefault(e["target"], []).append(e)
    result = {}
    for name, edges in incoming.items():
        requests = sum(e["requests"] for e in edges)
        failures = sum(e["error_rate"] * e["requests"] for e in edges)
        result[name] = NodeStats(
            requests=requests,
            error_rate=failures / requests if requests else 0.0,
            p95_ms=None,
            p99_ms=None,
            rps=sum(e["rps"] for e in edges),
        )
    return result


def _sick_by(verdict: Verdict) -> Literal["errors", "latency", "traffic", "unresponsive", None]:
    if verdict.state == "unresponsive":
        return "unresponsive"
    if verdict.rule is None:
        return None
    return {
        "error_rate": "errors",
        "availability": "errors",
        "p95_ms": "latency",
        "p99_ms": "latency",
        "rps": "traffic",
    }[verdict.rule.metric]  # type: ignore[return-value]

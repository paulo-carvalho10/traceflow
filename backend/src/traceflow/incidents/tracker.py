"""O ciclo de vida de um incidente: abre, acompanha, resolve, e conta tudo numa linha do tempo.

- **Abre** quando algum nó do projeto e ambiente sai de saudável (depois da histerese).
- **É atualizado** a cada segundo: causa, afetados, rotas de entrada, severidade. Cada mudança
  vira um acontecimento na linha do tempo.
- **Resolve** depois de 30 s com tudo saudável: uma falha que vai e volta continua sendo o
  mesmo incidente, em vez de abrir dez.

Um incidente por projeto e ambiente de cada vez: duas falhas ao mesmo tempo viram um incidente
com duas causas. O id nasce aqui (uuid), e não no banco, para o incidente aparecer na tela no
mesmo segundo em que abre, mesmo que a gravação demore ou precise ser repetida.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from traceflow.incidents.analysis import Severity
from traceflow.incidents.engine import Assessment, Channel
from traceflow.incidents.rules import SEVERITY_OF_STATE, State
from traceflow.incidents.text import STATE_LABEL, join_names, reason

RESOLVE_AFTER_S = 30.0
SEVERITY_RANK = {"SEV3": 1, "SEV2": 2, "SEV1": 3}


@dataclass
class Event:
    at: float
    kind: str  # opened, node_state, causes, severity, resolved
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Incident:
    project_id: int
    environment: str
    opened_at: float
    severity: Severity = "SEV3"
    peak_severity: Severity = "SEV3"
    title: str = ""
    causes: list[dict[str, Any]] = field(default_factory=list)
    affected: list[dict[str, Any]] = field(default_factory=list)
    at_risk: list[str] = field(default_factory=list)
    endpoints: list[dict[str, Any]] = field(default_factory=list)
    healthy_since: float | None = None
    resolved_at: float | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    worst: dict[str, State] = field(default_factory=dict)  # o pior estado que cada causa atingiu
    pending: list[Event] = field(default_factory=list)  # acontecimentos ainda não gravados
    dirty: bool = True  # o estado mudou desde a última gravação

    @property
    def status(self) -> str:
        return "open" if self.resolved_at is None else "resolved"

    def public(self) -> dict[str, Any]:
        """O que vai no retrato ao vivo, para a tela."""
        return {
            "id": self.id,
            "status": self.status,
            "severity": self.severity,
            "peak_severity": self.peak_severity,
            "title": self.title,
            "opened_at": _iso(self.opened_at),
            "causes": self.causes,
            "affected": self.affected,
            "at_risk": self.at_risk,
            "endpoints": self.endpoints,
        }

    def row(self) -> dict[str, Any]:
        """A linha da tabela incidents."""
        return {
            **{k: v for k, v in self.public().items() if k != "opened_at"},
            "project_id": self.project_id,
            "environment": self.environment,
            "opened_at": datetime.fromtimestamp(self.opened_at, tz=UTC),
            "resolved_at": datetime.fromtimestamp(self.resolved_at, tz=UTC) if self.resolved_at else None,
        }


class IncidentTracker:
    def __init__(self) -> None:
        self.open: dict[Channel, Incident] = {}
        self.unsaved: dict[str, Incident] = {}  # com estado ou acontecimentos por gravar

    def resume(self, incidents: list[Incident]) -> None:
        """Retoma os incidentes que estavam abertos (o processador reiniciou no meio de um)."""
        for incident in incidents:
            incident.dirty = False
            self.open[(incident.project_id, incident.environment)] = incident

    def step(self, channel: Channel, assessment: Assessment | None, now: float) -> Incident | None:
        """Avança um segundo. Devolve o incidente aberto deste canal (ou o que acabou de resolver)."""
        incident = self.open.get(channel)
        sick = assessment is not None and assessment.sick
        if incident is None:
            if not sick:
                return None
            assert assessment is not None
            incident = Incident(project_id=channel[0], environment=channel[1], opened_at=now)
            self.open[channel] = incident
            self._update(incident, assessment, now, opening=True)
        elif sick:
            assert assessment is not None
            incident.healthy_since = None
            self._update(incident, assessment, now, opening=False)
        else:
            if assessment is not None:
                self._node_events(incident, assessment, now)  # os "recuperou" de cada nó
            if incident.healthy_since is None:
                incident.healthy_since = now
            elif now - incident.healthy_since >= RESOLVE_AFTER_S:
                incident.resolved_at = now
                incident.dirty = True
                incident.pending.append(
                    Event(now, "resolved", f"Tudo saudável há {RESOLVE_AFTER_S:.0f} s: incidente resolvido")
                )
                del self.open[channel]
        self.unsaved[incident.id] = incident
        return incident

    def saved(self, incident: Incident, events: list[Event]) -> None:
        """A gravação deu certo: tira o que foi gravado da fila."""
        incident.pending = [e for e in incident.pending if e not in events]
        incident.dirty = False
        if not incident.pending:
            self.unsaved.pop(incident.id, None)

    def _update(self, incident: Incident, a: Assessment, now: float, *, opening: bool) -> None:
        verdicts = a.verdicts
        causes: list[dict[str, Any]] = [
            {"node": c.node, "state": verdicts[c.node].state, "reason": reason(verdicts[c.node]),
             "own": c.own, "virtual": c.node in a.virtual}
            for c in a.analysis.causes
        ]  # fmt: skip
        affected = [
            {"node": n, "state": verdicts[n].state, "reason": reason(verdicts[n])}
            for n in a.analysis.affected
        ]
        endpoints = [
            {"route": e.route, "service": e.service, "rps": e.rps, "error_rate": e.error_rate,
             "p95_ms": e.p95_ms, "baseline_ms": e.baseline_ms}
            for e in a.analysis.endpoints
        ]  # fmt: skip
        severity = a.analysis.severity
        cause_names: list[str] = [c["node"] for c in causes]
        # O título fica com o PIOR estado que a causa atingiu: na recuperação, o payments passa
        # por "degradado" antes de "saudável", e o incidente que foi "falhando" não pode
        # terminar no histórico como "degradado".
        for c in causes:
            before = incident.worst.get(c["node"], "healthy")
            if SEVERITY_OF_STATE[c["state"]] > SEVERITY_OF_STATE[before]:
                incident.worst[c["node"]] = c["state"]
        title = (
            f"{cause_names[0]} {STATE_LABEL[incident.worst[cause_names[0]]]}"
            if len(causes) == 1
            else f"{join_names(cause_names)} com problemas"
            if causes
            else "serviços com problemas"
        )

        if opening:
            incident.pending.append(
                Event(
                    now,
                    "opened",
                    f"Incidente aberto: {title} ({severity})",
                    {"severity": severity, "causes": cause_names},
                )
            )
        else:
            if cause_names != [c["node"] for c in incident.causes]:
                incident.pending.append(
                    Event(
                        now,
                        "causes",
                        f"Causa provável: {join_names(cause_names) or 'indefinida'}",
                        {"causes": cause_names},
                    )
                )
            if severity != incident.severity:
                verb = "subiu" if SEVERITY_RANK[severity] > SEVERITY_RANK[incident.severity] else "caiu"
                incident.pending.append(
                    Event(now, "severity", f"A severidade {verb}: {incident.severity} → {severity}",
                          {"from": incident.severity, "to": severity})
                )  # fmt: skip
        self._node_events(incident, a, now)

        changed = (title, causes, affected, a.analysis.at_risk, severity) != (
            incident.title, incident.causes, incident.affected, incident.at_risk, incident.severity,
        )  # fmt: skip
        incident.title, incident.causes, incident.affected = title, causes, affected
        incident.at_risk, incident.endpoints, incident.severity = a.analysis.at_risk, endpoints, severity
        if SEVERITY_RANK[severity] > SEVERITY_RANK[incident.peak_severity]:
            incident.peak_severity = severity
        # os números das rotas mudam a cada segundo: gravar só quando algo de fato mudou
        incident.dirty = incident.dirty or changed or opening

    def _node_events(self, incident: Incident, a: Assessment, now: float) -> None:
        for node, before, after in a.changes:
            text = f"{node}: {STATE_LABEL[before]} → {STATE_LABEL[after]}"
            if after != "healthy":
                text += f" ({reason(a.verdicts[node])})"
            incident.pending.append(
                Event(now, "node_state", text, {"node": node, "from": before, "to": after})
            )


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()

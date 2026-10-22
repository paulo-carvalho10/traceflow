"""Os incidentes de um projeto.

    GET /api/projects/{id}/incidents?status=open&environment=demo   a lista, os mais recentes primeiro
    GET /api/projects/{id}/incidents/{incident_id}                 o incidente, com:
        - a linha do tempo (o que o processador registrou, segundo a segundo);
        - a evidência dos traces: onde os erros NASCERAM (o span com falha sem filho com falha);
        - o antes / durante / depois de cada rota de entrada afetada.

Quem abre, atualiza e resolve é o processador (incidents/tracker.py). A API só lê, e calcula
sob demanda o que precisa dos spans gravados: a evidência e o antes / depois.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text

from traceflow.api.deps import DbDep, ReadableProject
from traceflow.models import Incident, IncidentEvent

router = APIRouter(prefix="/api/projects", tags=["incidentes"])

BEFORE_AFTER = timedelta(minutes=5)
EVIDENCE_MAX = timedelta(minutes=15)  # a evidência olha no máximo os 15 primeiros minutos


class IncidentSummary(BaseModel):
    id: str
    environment: str
    status: Literal["open", "resolved"]
    severity: str
    peak_severity: str
    title: str
    opened_at: datetime
    resolved_at: datetime | None
    causes: list[str]


class Event(BaseModel):
    at: datetime
    kind: str
    message: str
    data: dict[str, Any]


class ErrorOrigin(BaseModel):
    service: str
    origins: int  # quantos spans com falha, sem nenhum filho com falha, nasceram neste serviço
    share: float  # a fração do total


class Period(BaseModel):
    start: datetime
    end: datetime
    requests: int
    rps: float
    error_rate: float | None
    p95_ms: float | None


class EndpointComparison(BaseModel):
    route: str
    service: str
    before: Period
    worst: Period | None  # o pior minuto durante o incidente
    after: Period | None  # None enquanto o incidente não resolveu
    after_complete: bool  # os 5 minutos depois da recuperação já passaram


class IncidentDetail(IncidentSummary):
    causes_detail: list[dict[str, Any]]
    affected: list[dict[str, Any]]
    at_risk: list[str]
    endpoints: list[dict[str, Any]]
    events: list[Event]
    error_origins: list[ErrorOrigin]
    comparison: list[EndpointComparison]


def summary(i: Incident) -> IncidentSummary:
    return IncidentSummary(
        id=str(i.id), environment=i.environment, status=i.status, severity=i.severity,  # type: ignore[arg-type]
        peak_severity=i.peak_severity, title=i.title, opened_at=i.opened_at, resolved_at=i.resolved_at,
        causes=[c["node"] for c in i.causes],
    )  # fmt: skip


@router.get("/{project_id}/incidents")
async def list_incidents(
    project: ReadableProject,
    db: DbDep,
    status: Literal["open", "resolved"] | None = None,
    environment: str | None = None,
    limit: int = 50,
) -> list[IncidentSummary]:
    query = select(Incident).where(Incident.project_id == project.id)
    if status:
        query = query.where(Incident.status == status)
    if environment:
        query = query.where(Incident.environment == environment)
    rows = await db.scalars(query.order_by(Incident.opened_at.desc()).limit(min(max(limit, 1), 200)))
    return [summary(i) for i in rows]


# Onde os erros nasceram: o span com falha que não tem nenhum filho com falha. A mesma
# regra de falha do mapa (D49): 5xx ou sem resposta; um 4xx não é falha do sistema.
FAILED = "(({t}.http_status_code >= 500) OR ({t}.http_status_code IS NULL AND {t}.status = 'error'))"
ORIGINS_SQL = f"""
SELECT s.service, count(*) AS origins
FROM spans s
WHERE s.project_id = :project AND s.environment = :environment
  AND s.start_time >= :since AND s.start_time < :until
  AND {FAILED.format(t="s")}
  AND NOT EXISTS (
      SELECT 1 FROM spans c
      WHERE c.project_id = s.project_id AND c.trace_id = s.trace_id AND c.parent_span_id = s.span_id
        AND c.start_time >= :since - interval '1 minute' AND {FAILED.format(t="c")}
  )
GROUP BY s.service
ORDER BY origins DESC
LIMIT 5
"""

ROUTE = (
    "project_id = :project AND environment = :environment AND service = :service AND kind = 'server' "
    "AND parent_span_id IS NULL AND coalesce(http_method || ' ' || http_route, name) = :route"
)
PERIOD_SQL = f"""
SELECT count(*) AS requests,
       count(*) FILTER (WHERE status = 'error') AS errors,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
FROM spans WHERE {ROUTE} AND start_time >= :since AND start_time < :until
"""
WORST_MINUTE_SQL = f"""
SELECT time_bucket(interval '1 minute', start_time) AS minute,
       count(*) AS requests,
       count(*) FILTER (WHERE status = 'error') AS errors,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
FROM spans WHERE {ROUTE} AND start_time >= :since AND start_time < :until
GROUP BY minute
ORDER BY count(*) FILTER (WHERE status = 'error')::float / count(*) DESC, p95 DESC
LIMIT 1
"""


@router.get("/{project_id}/incidents/{incident_id}")
async def get_incident(incident_id: str, project: ReadableProject, db: DbDep) -> IncidentDetail:
    incident = await db.get(Incident, incident_id) if _looks_like_uuid(incident_id) else None
    if incident is None or incident.project_id != project.id:
        raise HTTPException(404, "incidente não encontrado")
    events = await db.scalars(
        select(IncidentEvent).where(IncidentEvent.incident_id == incident.id).order_by(IncidentEvent.at)
    )
    now = datetime.now(UTC)
    end = incident.resolved_at or now
    base = {"project": project.id, "environment": incident.environment}

    # a evidência: de 30 s antes de abrir até o fim (no máximo 15 minutos)
    since = incident.opened_at - timedelta(seconds=30)
    until = min(end, incident.opened_at + EVIDENCE_MAX)
    origins = (await db.execute(text(ORIGINS_SQL), {**base, "since": since, "until": until})).mappings().all()
    total = sum(r["origins"] for r in origins) or 1

    comparison = incident.summary.get("comparison") if incident.summary else None
    if comparison is None:
        comparison = [c.model_dump(mode="json") for c in await _compare(db, incident, base, now)]
        if incident.resolved_at and now >= incident.resolved_at + BEFORE_AFTER:
            incident.summary = {"comparison": comparison}  # completo: não muda mais, fica guardado
            await db.commit()

    return IncidentDetail(
        **summary(incident).model_dump(),
        causes_detail=incident.causes,
        affected=incident.affected,
        at_risk=incident.at_risk,
        endpoints=incident.endpoints,
        events=[Event(at=e.at, kind=e.kind, message=e.message, data=e.data) for e in events],
        error_origins=[
            ErrorOrigin(service=r["service"], origins=r["origins"], share=r["origins"] / total)
            for r in origins
        ],
        comparison=[EndpointComparison.model_validate(c) for c in comparison],
    )


async def _compare(
    db: DbDep, incident: Incident, base: dict[str, Any], now: datetime
) -> list[EndpointComparison]:
    result = []
    end = incident.resolved_at or now
    for endpoint in incident.endpoints:
        params = {**base, "service": endpoint["service"], "route": endpoint["route"]}
        before = await _period(db, params, incident.opened_at - BEFORE_AFTER, incident.opened_at)
        worst_row = (
            (await db.execute(text(WORST_MINUTE_SQL), {**params, "since": incident.opened_at, "until": end}))
            .mappings()
            .first()
        )
        worst = None
        if worst_row is not None:
            minute = worst_row["minute"]
            worst = _as_period(worst_row, minute, minute + timedelta(minutes=1))
        after = None
        if incident.resolved_at:
            after_end = min(now, incident.resolved_at + BEFORE_AFTER)
            after = await _period(db, params, incident.resolved_at, after_end)
        result.append(
            EndpointComparison(
                route=endpoint["route"],
                service=endpoint["service"],
                before=before,
                worst=worst,
                after=after,
                after_complete=bool(incident.resolved_at and now >= incident.resolved_at + BEFORE_AFTER),
            )
        )
    return result


async def _period(db: DbDep, params: dict[str, Any], since: datetime, until: datetime) -> Period:
    row = (await db.execute(text(PERIOD_SQL), {**params, "since": since, "until": until})).mappings().one()
    return _as_period(row, since, until)


def _as_period(row: Any, since: datetime, until: datetime) -> Period:
    requests = int(row["requests"] or 0)
    seconds = max((until - since).total_seconds(), 1.0)
    return Period(
        start=since,
        end=until,
        requests=requests,
        rps=requests / seconds,
        error_rate=row["errors"] / requests if requests else None,
        p95_ms=row["p95"],
    )


def _looks_like_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True

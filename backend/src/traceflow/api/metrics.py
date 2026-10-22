"""O histórico de um serviço.

    GET /api/projects/{id}/services/{name}/metrics      séries de taxa, erro, disponibilidade e percentis
    GET /api/projects/{id}/services/{name}/operations   as rotas que o serviço atendeu, cada uma com o seu RED

Os percentis aqui são EXATOS (percentile_cont sobre os spans gravados), diferente dos do
retrato ao vivo, que vêm de histogramas (erro < 10%). Num período longo a consulta pesa mais:
se ficar lenta, o próximo passo são os continuous aggregates do TimescaleDB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from traceflow.api.deps import DbDep, ReadableProject

router = APIRouter(prefix="/api/projects", tags=["serviços"])

MAX_RANGE = timedelta(days=3)
# Os spans dos últimos segundos ainda estão a caminho (lote do SDK, fila, processador, que
# segura 3 s pela marca d'água). O histórico para um pouco antes do "agora" para que o
# último ponto não mostre uma queda que é só atraso de entrega.
SETTLE = timedelta(seconds=5)


class MetricPoint(BaseModel):
    t: datetime
    requests: int
    rps: float
    error_rate: float | None
    availability: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None


class MetricSeries(BaseModel):
    service: str
    environment: str | None
    step_seconds: int
    points: list[MetricPoint]


class Operation(BaseModel):
    operation: str
    http_method: str | None
    requests: int
    error_rate: float
    p50_ms: float
    p95_ms: float


# time_bucket_gapfill: um ponto por intervalo, mesmo os sem dados (viram "0 requisições"
# no gráfico, em vez de a linha pular por cima do buraco e esconder que o serviço parou).
# Os CAST são necessários: a função tem várias versões, e sem o tipo explícito o PostgreSQL
# não sabe que :since e :until são horários (trataria como texto).
SERIES_SQL = """
SELECT time_bucket_gapfill(make_interval(secs => CAST(:step AS double precision)), start_time,
                           CAST(:since AS timestamptz), CAST(:until AS timestamptz)) AS t,
       count(*) AS requests,
       count(*) FILTER (WHERE status = 'error') AS errors,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99
FROM spans
WHERE {where}
GROUP BY t
ORDER BY t
"""

OPERATIONS_SQL = """
SELECT coalesce(http_route, name) AS operation, http_method,
       count(*) AS requests,
       count(*) FILTER (WHERE status = 'error') AS errors,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
FROM spans
WHERE {where}
GROUP BY 1, 2
ORDER BY requests DESC
LIMIT 50
"""


def step_for(span: timedelta) -> int:
    """Uns 60 pontos por gráfico, em passos redondos."""
    for seconds in (10, 30, 60, 300, 900, 1800, 3600):
        if span / timedelta(seconds=seconds) <= 72:
            return seconds
    return 3600


def _filters(
    project_id: int, service: str, environment: str | None, since: datetime, until: datetime
) -> tuple[str, dict[str, Any]]:
    where = [
        "project_id = :project",
        "service = :service",
        "kind = 'server'",
        "start_time >= :since",
        "start_time < :until",
    ]
    params: dict[str, Any] = {"project": project_id, "service": service, "since": since, "until": until}
    if environment is not None:
        where.append("environment = :environment")
        params["environment"] = environment
    return " AND ".join(where), params


def time_window(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    settled = datetime.now(UTC) - SETTLE
    until = min(until, settled) if until else settled
    since = since or until - timedelta(hours=1)
    if since >= until:
        raise HTTPException(422, "o início precisa ser antes do fim")
    return max(since, until - MAX_RANGE), until


@router.get("/{project_id}/services/{service}/metrics")
async def service_metrics(
    service: str,
    project: ReadableProject,
    db: DbDep,
    environment: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> MetricSeries:
    since, until = time_window(since, until)
    step = step_for(until - since)
    where, params = _filters(project.id, service, environment, since, until)
    rows = (await db.execute(text(SERIES_SQL.format(where=where)), {**params, "step": step})).mappings().all()
    points = []
    for row in rows:
        requests = int(row["requests"] or 0)
        errors = int(row["errors"] or 0)
        # Os baldes são alinhados no relógio (18:00, 18:01...), e o período não: o primeiro e
        # o último balde ficam só em parte dentro dele. Dividir pelo passo inteiro faria o
        # último ponto despencar (um minuto que ainda está enchendo); divide-se pelos
        # segundos que o balde realmente cobre.
        covered = (min(row["t"] + timedelta(seconds=step), until) - max(row["t"], since)).total_seconds()
        points.append(
            MetricPoint(
                t=row["t"],
                requests=requests,
                rps=requests / covered if covered > 0 else 0.0,
                error_rate=errors / requests if requests else None,
                availability=1 - errors / requests if requests else None,
                p50_ms=row["p50"],
                p95_ms=row["p95"],
                p99_ms=row["p99"],
            )
        )
    return MetricSeries(service=service, environment=environment, step_seconds=step, points=points)


@router.get("/{project_id}/services/{service}/operations")
async def service_operations(
    service: str,
    project: ReadableProject,
    db: DbDep,
    environment: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Operation]:
    since, until = time_window(since, until)
    where, params = _filters(project.id, service, environment, since, until)
    rows = (await db.execute(text(OPERATIONS_SQL.format(where=where)), params)).mappings().all()
    return [
        Operation(
            operation=row["operation"],
            http_method=row["http_method"],
            requests=row["requests"],
            error_rate=row["errors"] / row["requests"],
            p50_ms=row["p50"],
            p95_ms=row["p95"],
        )
        for row in rows
    ]

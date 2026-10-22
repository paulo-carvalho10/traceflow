"""O mapa de serviços de um período passado.

    GET /api/projects/{id}/map?environment=demo&since=...&until=...

O mapa AO VIVO vem no retrato de cada segundo, pelo WebSocket (live/aggregator.py). Esta rota
responde "como estava o mapa entre 18:15 e 18:30?", com o mesmo formato, para o front desenhar
os dois com o mesmo código.

- Os serviços (nós) vêm dos spans SERVER: o que cada um atendeu, e quanto ENTROU por ele.
- As ligações vêm dos spans CLIENT, do lado de quem chama (D9). O serviço por trás de cada
  endereço vem do catálogo de endereços; endereço sem catálogo é um nó virtual.
- Falha de uma ligação é 5xx ou falta de resposta, como no ao vivo (D49). As duas regras
  precisam andar juntas: um teste confere as duas com os mesmos spans.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from traceflow.api.deps import DbDep, ReadableProject
from traceflow.api.metrics import time_window

router = APIRouter(prefix="/api/projects", tags=["mapa"])


class MapService(BaseModel):
    name: str
    requests: int
    rps: float
    error_rate: float
    p50_ms: float | None
    p95_ms: float | None
    entry_rps: float  # as requisições que entraram no sistema por este serviço


class MapEdge(BaseModel):
    source: str
    target: str  # o serviço, ou o próprio endereço quando ninguém o atendeu com um span
    address: str
    virtual: bool
    requests: int
    rps: float
    error_rate: float
    p50_ms: float | None
    p95_ms: float | None


class ServiceMap(BaseModel):
    environment: str
    since: datetime
    until: datetime
    services: list[MapService]
    edges: list[MapEdge]


SERVICES_SQL = """
SELECT service AS name,
       count(*) AS requests,
       count(*) FILTER (WHERE status = 'error') AS errors,
       count(*) FILTER (WHERE parent_span_id IS NULL) AS entries,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
FROM spans
WHERE project_id = :project AND environment = :environment AND kind = 'server'
  AND start_time >= :since AND start_time < :until
GROUP BY service
ORDER BY service
"""

EDGES_SQL = """
SELECT c.service AS source, c.peer_address AS address, a.service AS target,
       count(*) AS requests,
       count(*) FILTER (WHERE c.http_status_code >= 500
                           OR (c.http_status_code IS NULL AND c.status = 'error')) AS failures,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY c.duration_ms) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY c.duration_ms) AS p95
FROM spans c
LEFT JOIN service_addresses a
       ON a.project_id = c.project_id AND a.environment = c.environment AND a.address = c.peer_address
WHERE c.project_id = :project AND c.environment = :environment AND c.kind = 'client'
  AND c.peer_address IS NOT NULL
  AND c.start_time >= :since AND c.start_time < :until
GROUP BY c.service, c.peer_address, a.service
ORDER BY c.service, c.peer_address
"""


@router.get("/{project_id}/map")
async def service_map(
    project: ReadableProject,
    db: DbDep,
    environment: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> ServiceMap:
    since, until = time_window(since, until)
    seconds = (until - since).total_seconds()
    params = {"project": project.id, "environment": environment, "since": since, "until": until}

    services = [
        MapService(
            name=r["name"],
            requests=r["requests"],
            rps=r["requests"] / seconds,
            error_rate=r["errors"] / r["requests"],
            p50_ms=r["p50"],
            p95_ms=r["p95"],
            entry_rps=r["entries"] / seconds,
        )
        for r in (await db.execute(text(SERVICES_SQL), params)).mappings()
    ]
    edges = [
        MapEdge(
            source=r["source"],
            target=r["target"] or r["address"],
            address=r["address"],
            virtual=r["target"] is None,
            requests=r["requests"],
            rps=r["requests"] / seconds,
            error_rate=r["failures"] / r["requests"],
            p50_ms=r["p50"],
            p95_ms=r["p95"],
        )
        for r in (await db.execute(text(EDGES_SQL), params)).mappings()
    ]
    return ServiceMap(environment=environment, since=since, until=until, services=services, edges=edges)

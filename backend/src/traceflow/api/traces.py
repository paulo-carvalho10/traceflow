"""Busca de traces e o trace completo (o waterfall).

    GET /api/projects/{id}/traces               traces (pelos spans raiz), mais recentes primeiro
    GET /api/projects/{id}/traces/{trace_id}    todos os spans, em árvore, prontos para o waterfall

As consultas são SQL escrito à mão (D20), executadas pelo mesmo pool do SQLAlchemy.

A paginação é por cursor, não por número de página: a próxima página começa "depois do
último trace que você viu" (horário e trace_id). Com OFFSET, a página 50 obrigaria o banco
a contar e descartar 49 páginas, e traces chegando sem parar fariam itens pularem de página.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from traceflow.api.deps import DbDep, ReadableProject
from traceflow.traces import RawSpan, build_tree

router = APIRouter(prefix="/api/projects", tags=["traces"])

MAX_RANGE = timedelta(days=3)  # a retenção: além disso não há dados
TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


class TraceSummary(BaseModel):
    trace_id: str
    environment: str
    service: str  # o serviço da raiz: a porta de entrada
    name: str
    http_method: str | None
    http_status_code: int | None
    start_time: datetime
    duration_ms: float
    span_count: int
    error_count: int
    service_count: int


class TracePage(BaseModel):
    traces: list[TraceSummary]
    next_cursor: str | None  # None: não há mais páginas


class SpanOut(BaseModel):
    span_id: str
    parent_span_id: str | None
    depth: int
    offset_ms: float
    duration_ms: float
    self_time_ms: float
    orphan: bool
    children: int
    service: str
    name: str
    kind: str
    status: str
    status_message: str | None
    http_method: str | None
    http_route: str | None
    http_status_code: int | None
    peer_address: str | None
    attributes: dict[str, Any]
    resource: dict[str, Any]
    events: list[dict[str, Any]]


class TraceOut(BaseModel):
    trace_id: str
    start_time: datetime
    duration_ms: float
    services: list[str]
    error_count: int
    spans: list[SpanOut]


# Os números do trace inteiro (spans, erros, serviços) vêm de uma subconsulta por raiz.
# O intervalo de tempo em volta da raiz faz o banco só abrir as partições daquele horário.
LIST_SQL = """
SELECT r.trace_id, r.environment, r.service, r.name, r.http_method, r.http_status_code,
       r.start_time, r.duration_ms, c.span_count, c.error_count, c.service_count
FROM spans r
CROSS JOIN LATERAL (
    SELECT count(*) AS span_count,
           count(*) FILTER (WHERE s.status = 'error') AS error_count,
           count(DISTINCT s.service) AS service_count
    FROM spans s
    WHERE s.project_id = r.project_id AND s.trace_id = r.trace_id
      AND s.start_time BETWEEN r.start_time - interval '1 minute' AND r.start_time + interval '10 minutes'
) c
WHERE {where}
ORDER BY r.start_time DESC, r.trace_id DESC
LIMIT :limit
"""

DETAIL_SQL = """
SELECT span_id, parent_span_id, service, name, kind, start_time, duration_ms, status, status_message,
       http_method, http_route, http_status_code, peer_address, attributes, resource, events
FROM spans
WHERE project_id = :project AND trace_id = :trace {window}
ORDER BY start_time
"""


@router.get("/{project_id}/traces")
async def search_traces(
    project: ReadableProject,
    db: DbDep,
    environment: str | None = None,
    service: str | None = None,
    through: Annotated[
        str | None, Query(description="traces que passaram por este serviço, em qualquer ponto")
    ] = None,
    operation: Annotated[
        str | None, Query(max_length=200, description="trecho do nome, como '/checkout'")
    ] = None,
    status: Literal["error", "ok"] | None = None,
    min_duration_ms: Annotated[float | None, Query(ge=0)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> TracePage:
    until = until or datetime.now(UTC)
    since = since or until - timedelta(hours=1)
    if since >= until:
        raise HTTPException(422, "o início precisa ser antes do fim")
    since = max(since, until - MAX_RANGE)

    where = [
        "r.project_id = :project",
        "r.parent_span_id IS NULL",
        "r.start_time >= :since",
        "r.start_time < :until",
    ]
    params: dict[str, Any] = {"project": project.id, "since": since, "until": until, "limit": limit + 1}
    if environment is not None:
        where.append("r.environment = :environment")
        params["environment"] = environment
    if service is not None:
        where.append("r.service = :service")
        params["service"] = service
    if through is not None:
        # passou pelo serviço em qualquer ponto do trace, não só na porta de entrada
        where.append(
            "EXISTS (SELECT 1 FROM spans t WHERE t.project_id = r.project_id AND t.trace_id = r.trace_id "
            "AND t.service = :through AND t.start_time BETWEEN r.start_time - interval '1 minute' "
            "AND r.start_time + interval '10 minutes')"
        )
        params["through"] = through
    if operation:
        where.append("r.name ILIKE :operation ESCAPE '\\'")
        params["operation"] = f"%{_escape_like(operation)}%"
    if min_duration_ms is not None:
        where.append("r.duration_ms >= :min_duration")
        params["min_duration"] = min_duration_ms
    if status == "error":
        where.append("c.error_count > 0")
    elif status == "ok":
        where.append("c.error_count = 0")
    if cursor is not None:
        after_time, after_trace = decode_cursor(cursor)
        where.append("(r.start_time, r.trace_id) < (:after_time, :after_trace)")
        params |= {"after_time": after_time, "after_trace": after_trace}

    rows = (await db.execute(text(LIST_SQL.format(where=" AND ".join(where))), params)).mappings().all()
    traces = [TraceSummary.model_validate(dict(row)) for row in rows[:limit]]
    has_more = len(rows) > limit
    return TracePage(
        traces=traces,
        next_cursor=encode_cursor(traces[-1].start_time, traces[-1].trace_id) if has_more else None,
    )


@router.get("/{project_id}/traces/{trace_id}")
async def get_trace(
    trace_id: str,
    project: ReadableProject,
    db: DbDep,
    around: Annotated[
        datetime | None, Query(description="horário aproximado, para o banco só abrir aquelas partições")
    ] = None,
) -> TraceOut:
    trace_id = trace_id.lower()
    if not TRACE_ID.match(trace_id):
        raise HTTPException(404, "trace não encontrado")
    params: dict[str, Any] = {"project": project.id, "trace": trace_id}
    window = ""
    if around is not None:
        window = "AND start_time BETWEEN :window_start AND :window_end"
        params |= {"window_start": around - timedelta(hours=1), "window_end": around + timedelta(hours=1)}
    rows = (await db.execute(text(DETAIL_SQL.format(window=window)), params)).mappings().all()
    if not rows:
        raise HTTPException(404, "trace não encontrado")
    tree = build_tree([RawSpan(**dict(row)) for row in rows])
    return TraceOut(
        trace_id=trace_id,
        start_time=tree.start_time,
        duration_ms=tree.duration_ms,
        services=tree.services,
        error_count=tree.error_count,
        spans=[
            SpanOut(
                **{k: getattr(t.span, k) for k in SPAN_FIELDS},
                depth=t.depth,
                offset_ms=t.offset_ms,
                self_time_ms=t.self_time_ms,
                orphan=t.orphan,
                children=t.children,
            )
            for t in tree.spans
        ],
    )


SPAN_FIELDS = (
    "span_id", "parent_span_id", "duration_ms", "service", "name", "kind", "status", "status_message",
    "http_method", "http_route", "http_status_code", "peer_address", "attributes", "resource", "events",
)  # fmt: skip


def encode_cursor(start_time: datetime, trace_id: str) -> str:
    return base64.urlsafe_b64encode(f"{start_time.isoformat()}|{trace_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        moment, trace_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        if not TRACE_ID.match(trace_id):
            raise ValueError(trace_id)
        return datetime.fromisoformat(moment), trace_id
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise HTTPException(422, "cursor inválido") from exc


def _escape_like(term: str) -> str:
    """'%' e '_' digitados pela pessoa são texto, não curingas do LIKE."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

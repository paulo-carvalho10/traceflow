"""De OTLP para uma linha da tabela `spans`.

Os campos que as telas mais consultam (serviço, rota, status HTTP, destino de uma chamada)
viram colunas próprias. O resto vai para JSONB.

Aceita os nomes novos e os antigos das convenções semânticas do HTTP: aplicações de fora
podem estar em qualquer versão da instrumentação.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span

KINDS = {1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer"}
STATUSES = {0: "unset", 1: "ok", 2: "error"}

HTTP_METHOD = ("http.request.method", "http.method")
HTTP_STATUS = ("http.response.status_code", "http.status_code")
HTTP_ROUTE = ("http.route",)
PEER_HOST = ("server.address", "net.peer.name")
PEER_PORT = ("server.port", "net.peer.port")
ENVIRONMENT = ("deployment.environment.name", "deployment.environment")

MAX_TEXT = 8_192  # um atributo gigante não pode inflar a linha
MAX_EVENTS = 50

COLUMNS = (
    "project_id", "environment", "trace_id", "span_id", "parent_span_id", "service", "name", "kind",
    "start_time", "duration_ms", "status", "status_message", "http_method", "http_route",
    "http_status_code", "peer_address", "attributes", "resource", "events",
)  # fmt: skip


@dataclass(frozen=True)
class SpanRow:
    project_id: int
    environment: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    name: str
    kind: str
    start_time: datetime
    duration_ms: float
    status: str
    status_message: str | None
    http_method: str | None
    http_route: str | None
    http_status_code: int | None
    peer_address: str | None
    attributes: dict[str, Any]
    resource: dict[str, Any]
    events: list[dict[str, Any]]

    def as_record(self) -> tuple[Any, ...]:
        return tuple(getattr(self, c) for c in COLUMNS)


@dataclass
class Normalized:
    rows: list[SpanRow] = field(default_factory=list)
    out_of_window: int = 0  # descartados por horário fora da janela aceita


def normalize(
    export: ExportTraceServiceRequest,
    project_id: int,
    *,
    now_ns: int,
    accept_past_s: int,
    accept_future_s: int,
) -> Normalized:
    result = Normalized()
    oldest = now_ns - accept_past_s * 1_000_000_000
    newest = now_ns + accept_future_s * 1_000_000_000
    for resource_spans in export.resource_spans:
        resource = attributes_to_dict(resource_spans.resource.attributes)
        service = text(resource.pop("service.name", None)) or "unknown_service"
        environment = text(_pop_first(resource, ENVIRONMENT)) or "default"
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                if not oldest <= span.start_time_unix_nano <= newest:
                    result.out_of_window += 1
                    continue
                result.rows.append(_row(span, project_id, environment, service, resource))
    return result


def _row(span: Span, project_id: int, environment: str, service: str, resource: dict[str, Any]) -> SpanRow:
    attrs = attributes_to_dict(span.attributes)
    kind = KINDS.get(span.kind, "internal")
    peer = None
    if kind in ("client", "producer"):
        host, port = _pop_first(attrs, PEER_HOST), _pop_first(attrs, PEER_PORT)
        peer = f"{host}:{port}" if host and port else text(host)
    status_code = _pop_first(attrs, HTTP_STATUS)
    return SpanRow(
        project_id=project_id,
        environment=environment,
        trace_id=span.trace_id.hex(),
        span_id=span.span_id.hex(),
        parent_span_id=span.parent_span_id.hex() or None,
        service=service,
        name=text(span.name) or "(sem nome)",
        kind=kind,
        start_time=datetime.fromtimestamp(span.start_time_unix_nano / 1e9, tz=UTC),
        duration_ms=max(0, span.end_time_unix_nano - span.start_time_unix_nano) / 1e6,
        status=STATUSES.get(span.status.code, "unset"),
        status_message=text(span.status.message) or None,
        http_method=text(_pop_first(attrs, HTTP_METHOD)) or None,
        http_route=text(_pop_first(attrs, HTTP_ROUTE)) or None,
        http_status_code=status_code if isinstance(status_code, int) else None,
        peer_address=peer,
        attributes=attrs,
        resource=resource,
        events=_events(span),
    )


def _events(span: Span) -> list[dict[str, Any]]:
    """Eventos do span, como uma exceção registrada, com o horário relativo ao início do span."""
    return [
        {
            "name": text(e.name),
            "offset_ms": (e.time_unix_nano - span.start_time_unix_nano) / 1e6,
            "attributes": attributes_to_dict(e.attributes),
        }
        for e in span.events[:MAX_EVENTS]
    ]


def attributes_to_dict(attributes: Iterable[KeyValue]) -> dict[str, Any]:
    return {text(kv.key): any_value(kv.value) for kv in attributes}


def any_value(value: AnyValue) -> Any:
    """Converte um AnyValue do OTLP num valor que o JSONB do PostgreSQL aceita."""
    match value.WhichOneof("value"):
        case "string_value":
            return text(value.string_value)
        case "bool_value":
            return value.bool_value
        case "int_value":
            return value.int_value
        case "double_value":
            d = value.double_value
            # JSON não tem NaN nem infinito, e o PostgreSQL recusaria a linha inteira
            return d if math.isfinite(d) else str(d)
        case "array_value":
            return [any_value(v) for v in value.array_value.values]
        case "kvlist_value":
            return attributes_to_dict(value.kvlist_value.values)
        case "bytes_value":
            return base64.b64encode(value.bytes_value).decode()
    return None


def text(value: Any) -> str:
    """Texto que o PostgreSQL aceita: sem o caractere nulo (\\x00) e com tamanho limitado."""
    if value is None:
        return ""
    s = value if isinstance(value, str) else str(value)
    return s.replace("\x00", "")[:MAX_TEXT]


def _pop_first(attrs: dict[str, Any], keys: Sequence[str]) -> Any:
    """Tira do dicionário o primeiro nome que existir (o novo antes do antigo) e remove os outros."""
    found = None
    for key in keys:
        if key in attrs:
            value = attrs.pop(key)
            if found is None:
                found = value
    return found

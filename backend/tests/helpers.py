"""Monta requisições OTLP de exemplo para os testes."""

from __future__ import annotations

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

TRACE_ID = bytes.fromhex("5b8efff798038103d269b633813fc60c")
SPAN_ID = bytes.fromhex("eee19b7ec3c1b174")
PARENT_ID = bytes.fromhex("eee19b7ec3c1b173")


def export_request(services: dict[str, int], trace_id: bytes = TRACE_ID) -> ExportTraceServiceRequest:
    """Uma requisição com `n` spans para cada serviço: {"orders": 2, "payments": 1}."""
    request = ExportTraceServiceRequest()
    for service, n in services.items():
        rs = ResourceSpans(
            resource=Resource(attributes=[KeyValue(key="service.name", value=AnyValue(string_value=service))])
        )
        ss = ScopeSpans()
        for i in range(n):
            ss.spans.append(
                Span(
                    trace_id=trace_id,
                    span_id=(i + 1).to_bytes(8, "big"),
                    parent_span_id=PARENT_ID,
                    name="POST /orders",
                    kind=Span.SPAN_KIND_SERVER,
                    start_time_unix_nano=1_700_000_000_000_000_000,
                    end_time_unix_nano=1_700_000_000_050_000_000,
                )
            )
        rs.scope_spans.append(ss)
        request.resource_spans.append(rs)
    return request


# O exemplo da especificação do OTLP/JSON: ids em hexadecimal, enum como número.
JSON_EXAMPLE = {
    "resourceSpans": [
        {
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "orders"}}]},
            "scopeSpans": [
                {
                    "scope": {"name": "manual"},
                    "spans": [
                        {
                            "traceId": "5B8EFFF798038103D269B633813FC60C",
                            "spanId": "EEE19B7EC3C1B174",
                            "parentSpanId": "EEE19B7EC3C1B173",
                            "name": "POST /orders",
                            "kind": 2,
                            "startTimeUnixNano": "1700000000000000000",
                            "endTimeUnixNano": "1700000000050000000",
                            "campoQueAindaNaoExiste": 42,
                        }
                    ],
                }
            ],
        }
    ]
}

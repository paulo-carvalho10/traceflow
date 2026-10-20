from __future__ import annotations

import math

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, ArrayValue, KeyValue, KeyValueList
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

from traceflow.normalize import SpanRow, any_value, normalize

NOW = 1_760_900_000_000_000_000  # 19/10/2025, em nanossegundos
DAY = 24 * 3600


def kv(key: str, value: object) -> KeyValue:
    if isinstance(value, bool):
        return KeyValue(key=key, value=AnyValue(bool_value=value))
    if isinstance(value, int):
        return KeyValue(key=key, value=AnyValue(int_value=value))
    if isinstance(value, float):
        return KeyValue(key=key, value=AnyValue(double_value=value))
    return KeyValue(key=key, value=AnyValue(string_value=str(value)))


def export(span: Span, resource: dict[str, object] | None = None) -> ExportTraceServiceRequest:
    resource = (
        {"service.name": "orders", "deployment.environment.name": "demo"} if resource is None else resource
    )
    return ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource=Resource(attributes=[kv(k, v) for k, v in resource.items()]),
                scope_spans=[ScopeSpans(spans=[span])],
            )
        ]
    )


def span(**overrides: object) -> Span:
    base: dict[str, object] = {
        "trace_id": bytes.fromhex("5b8efff798038103d269b633813fc60c"),
        "span_id": bytes.fromhex("eee19b7ec3c1b174"),
        "name": "POST /orders",
        "kind": Span.SPAN_KIND_SERVER,
        "start_time_unix_nano": NOW - 1_000_000_000,
        "end_time_unix_nano": NOW - 1_000_000_000 + 42_500_000,
    }
    base.update(overrides)
    return Span(**base)  # type: ignore[arg-type]


def run(request: ExportTraceServiceRequest) -> tuple[list[SpanRow], int]:
    result = normalize(request, 7, now_ns=NOW, accept_past_s=3 * DAY, accept_future_s=600)
    return result.rows, result.out_of_window


def test_span_server_vira_linha_com_as_colunas_principais() -> None:
    s = span(
        attributes=[kv("http.request.method", "POST"), kv("http.route", "/orders"),
                    kv("http.response.status_code", 201), kv("user_agent.original", "httpx")],
    )  # fmt: skip
    [row], _ = run(export(s))
    assert (row.project_id, row.environment, row.service) == (7, "demo", "orders")
    assert row.trace_id == "5b8efff798038103d269b633813fc60c"
    assert row.parent_span_id is None  # sem pai: é a raiz
    assert (row.kind, row.status) == ("server", "unset")
    assert (row.http_method, row.http_route, row.http_status_code) == ("POST", "/orders", 201)
    assert row.duration_ms == 42.5
    assert row.attributes == {"user_agent.original": "httpx"}  # o que virou coluna sai do JSON


def test_span_client_guarda_o_destino_da_chamada() -> None:
    s = span(kind=Span.SPAN_KIND_CLIENT, parent_span_id=b"\x01" * 8,
             attributes=[kv("server.address", "payments"), kv("server.port", 8000)])  # fmt: skip
    [row], _ = run(export(s))
    assert row.kind == "client"
    assert row.peer_address == "payments:8000"
    assert row.parent_span_id == "01" * 8


def test_nomes_antigos_das_convencoes_tambem_valem() -> None:
    old_names = [kv("http.method", "GET"), kv("http.status_code", 503), kv("net.peer.name", "bank")]
    s = span(kind=Span.SPAN_KIND_CLIENT, attributes=old_names)
    [row], _ = run(export(s, {"service.name": "legado", "deployment.environment": "prod"}))
    assert (row.http_method, row.http_status_code, row.peer_address) == ("GET", 503, "bank")
    assert row.environment == "prod"


def test_sem_servico_nem_ambiente_usa_padroes() -> None:
    [row], _ = run(export(span(), resource={}))
    assert (row.service, row.environment) == ("unknown_service", "default")


def test_status_de_erro_e_eventos_de_excecao() -> None:
    exc = Span.Event(time_unix_nano=NOW - 1_000_000_000 + 10_000_000, name="exception",
                     attributes=[kv("exception.type", "TimeoutError")])  # fmt: skip
    s = span(status=Status(code=Status.STATUS_CODE_ERROR, message="tempo esgotado"), events=[exc])
    [row], _ = run(export(s))
    assert (row.status, row.status_message) == ("error", "tempo esgotado")
    assert row.events == [
        {"name": "exception", "offset_ms": 10.0, "attributes": {"exception.type": "TimeoutError"}}
    ]


def test_spans_fora_da_janela_sao_descartados() -> None:
    velho = span(start_time_unix_nano=NOW - 4 * DAY * 10**9, end_time_unix_nano=NOW - 4 * DAY * 10**9 + 1)
    futuro = span(start_time_unix_nano=NOW + 3600 * 10**9, end_time_unix_nano=NOW + 3600 * 10**9 + 1)
    zero = span(start_time_unix_nano=0, end_time_unix_nano=0)  # horário "não preenchido": 1970
    rows, out = run(ExportTraceServiceRequest(resource_spans=[
        *export(velho).resource_spans, *export(futuro).resource_spans,
        *export(zero).resource_spans, *export(span()).resource_spans,
    ]))  # fmt: skip
    assert (len(rows), out) == (1, 3)


def test_texto_e_numeros_que_o_postgres_recusaria_sao_limpos() -> None:
    s = span(name="POST /a\x00b", attributes=[kv("chave\x00", "valor\x00"), kv("taxa", math.nan)])
    [row], _ = run(export(s))
    assert row.name == "POST /ab"
    assert row.attributes == {"chave": "valor", "taxa": "nan"}


def test_duracao_negativa_vira_zero() -> None:
    [row], _ = run(export(span(end_time_unix_nano=NOW - 2_000_000_000)))
    assert row.duration_ms == 0


def test_any_value_converte_listas_e_mapas_aninhados() -> None:
    value = AnyValue(
        kvlist_value=KeyValueList(values=[
            KeyValue(key="ids", value=AnyValue(array_value=ArrayValue(values=[
                AnyValue(int_value=1), AnyValue(int_value=2)]))),
            KeyValue(key="raw", value=AnyValue(bytes_value=b"\x00\xff")),
            KeyValue(key="ok", value=AnyValue(bool_value=True)),
        ])
    )  # fmt: skip
    assert any_value(value) == {"ids": [1, 2], "raw": "AP8=", "ok": True}
    assert any_value(AnyValue()) is None

from __future__ import annotations

import gzip
import json

import pytest
from helpers import JSON_EXAMPLE, PARENT_ID, SPAN_ID, TRACE_ID, export_request

from traceflow import otlp


def test_protobuf_ida_e_volta() -> None:
    original = export_request({"orders": 2, "payments": 1})
    parsed = otlp.parse_request(original.SerializeToString(), otlp.PROTOBUF)
    assert parsed == original
    assert otlp.count_spans(parsed) == 3


def test_json_com_ids_em_hexadecimal_vira_os_mesmos_bytes() -> None:
    parsed = otlp.parse_request(json.dumps(JSON_EXAMPLE).encode(), otlp.JSON)
    span = parsed.resource_spans[0].scope_spans[0].spans[0]
    assert span.trace_id == TRACE_ID
    assert span.span_id == SPAN_ID
    assert span.parent_span_id == PARENT_ID
    assert span.kind == 2
    assert span.end_time_unix_nano - span.start_time_unix_nano == 50_000_000


def test_json_com_id_que_nao_e_hexadecimal_e_recusado() -> None:
    doc = json.loads(json.dumps(JSON_EXAMPLE))
    doc["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"] = "não-é-hex"
    with pytest.raises(otlp.InvalidPayload, match="traceId"):
        otlp.parse_request(json.dumps(doc).encode(), otlp.JSON)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"\xff\xff\xff isto nao e protobuf", otlp.PROTOBUF),
        (b"{nao e json", otlp.JSON),
        (b"[1, 2, 3]", otlp.JSON),
        (b'{"resourceSpans": "deveria ser lista"}', otlp.JSON),
    ],
    ids=["protobuf", "json-quebrado", "json-lista", "json-fora-do-formato"],
)
def test_corpo_invalido_e_recusado(body: bytes, content_type: str) -> None:
    with pytest.raises(otlp.InvalidPayload):
        otlp.parse_request(body, content_type)


def test_media_type_ignora_parametros_e_maiusculas() -> None:
    assert otlp.media_type("Application/JSON; charset=utf-8") == otlp.JSON
    assert otlp.media_type(None) == ""


def test_gzip_e_descomprimido() -> None:
    body = export_request({"orders": 1}).SerializeToString()
    assert otlp.decompress(gzip.compress(body), "gzip", limit=10_000) == body
    assert otlp.decompress(body, None, limit=10_000) == body


def test_bomba_de_compressao_para_no_limite() -> None:
    bomba = gzip.compress(b"\0" * 5_000_000)  # 5 MB de zeros viram uns 5 KB comprimidos
    assert len(bomba) < 10_000
    with pytest.raises(otlp.PayloadTooLarge):
        otlp.decompress(bomba, "gzip", limit=1_000_000)


def test_gzip_quebrado_e_codificacao_desconhecida() -> None:
    with pytest.raises(otlp.InvalidPayload):
        otlp.decompress(b"isto nao e gzip", "gzip", limit=1000)
    with pytest.raises(otlp.UnsupportedMediaType):
        otlp.decompress(b"abc", "br", limit=1000)


def test_resposta_no_mesmo_formato_da_requisicao() -> None:
    assert otlp.success_response(otlp.JSON) == b"{}"
    assert otlp.success_response(otlp.PROTOBUF) == b""  # ExportTraceServiceResponse vazio

"""Leitura de requisições OTLP/HTTP de traces (a especificação está em opentelemetry.io/docs/specs/otlp).

O corpo pode chegar em protobuf ou em JSON, comprimido ou não. Tudo vira um
ExportTraceServiceRequest: o mesmo formato, venha de onde vier.
"""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any

from google.protobuf import json_format
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

PROTOBUF = "application/x-protobuf"
JSON = "application/json"
SUPPORTED = (PROTOBUF, JSON)

ID_FIELDS = ("traceId", "spanId", "parentSpanId")


class OtlpError(Exception):
    status_code = 400


class UnsupportedMediaType(OtlpError):
    status_code = 415


class PayloadTooLarge(OtlpError):
    status_code = 413


class InvalidPayload(OtlpError):
    status_code = 400


def media_type(content_type: str | None) -> str:
    """'application/json; charset=utf-8' -> 'application/json'."""
    return (content_type or "").split(";")[0].strip().lower()


def decompress(body: bytes, encoding: str | None, limit: int) -> bytes:
    """Descomprime gzip com um teto de tamanho.

    O teto vale para o resultado, não para o que chegou: 4 MB de gzip podem virar 4 GB
    (uma "bomba de compressão"). Descomprimir com max_length para no limite sem estourar a memória.
    """
    encoding = (encoding or "identity").strip().lower()
    if encoding == "identity":
        return body
    if encoding != "gzip":
        raise UnsupportedMediaType(f"Content-Encoding {encoding} não suportado (use gzip ou nenhum)")
    inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)  # 16+: espera o cabeçalho gzip
    try:
        data = inflater.decompress(body, limit + 1)
    except zlib.error as exc:
        raise InvalidPayload(f"gzip inválido: {exc}") from exc
    if len(data) > limit or inflater.unconsumed_tail:
        raise PayloadTooLarge(f"descomprimido passa de {limit} bytes")
    return data


def parse_request(body: bytes, content_type: str) -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    if content_type == PROTOBUF:
        try:
            request.ParseFromString(body)
        except DecodeError as exc:
            raise InvalidPayload(f"protobuf inválido: {exc}") from exc
        return request
    if content_type == JSON:
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidPayload(f"JSON inválido: {exc}") from exc
        if not isinstance(document, dict):
            raise InvalidPayload("o JSON precisa ser um objeto")
        _hex_ids_to_base64(document)
        try:
            # campos desconhecidos são ignorados: a especificação manda aceitar versões mais novas
            json_format.ParseDict(document, request, ignore_unknown_fields=True)
        except json_format.ParseError as exc:
            raise InvalidPayload(f"JSON fora do formato OTLP: {exc}") from exc
        return request
    raise UnsupportedMediaType(f"Content-Type {content_type or '(vazio)'} não suportado")


def _hex_ids_to_base64(document: dict[str, Any]) -> None:
    """No OTLP/JSON os ids vêm em hexadecimal, mas o mapeamento padrão de protobuf para JSON espera base64.

    É uma exceção da especificação do OTLP: sem esta conversão, um traceId válido seria rejeitado
    (ou, pior, lido como outros bytes).
    """
    for resource_spans in _objects(document.get("resourceSpans")):
        for scope_spans in _objects(resource_spans.get("scopeSpans")):
            for span in _objects(scope_spans.get("spans")):
                _convert_ids(span)
                for link in _objects(span.get("links")):
                    _convert_ids(link)


def _objects(value: Any) -> list[dict[str, Any]]:
    """Só os objetos de uma lista. Fora do formato esperado, devolve nada e deixa o ParseDict recusar."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _convert_ids(obj: dict[str, Any]) -> None:
    for field in ID_FIELDS:
        value = obj.get(field)
        if isinstance(value, str) and value:
            try:
                obj[field] = base64.b64encode(bytes.fromhex(value)).decode()
            except ValueError as exc:
                raise InvalidPayload(f"{field} não é hexadecimal: {value!r}") from exc


def count_spans(request: ExportTraceServiceRequest) -> int:
    return sum(len(ss.spans) for rs in request.resource_spans for ss in rs.scope_spans)


def success_response(content_type: str) -> bytes:
    """A resposta de sucesso vai no mesmo formato da requisição, como manda a especificação."""
    if content_type == JSON:
        return b"{}"
    return bytes(ExportTraceServiceResponse().SerializeToString())

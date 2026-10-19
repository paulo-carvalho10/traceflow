"""O contrato entre a ingestão e o processador: o que vai em cada entrada do Redis Stream.

Uma entrada é um lote inteiro (uma requisição OTLP), não um span: menos operações no Redis,
e o processador decodifica o lote de uma vez.

O processador apaga as entradas que já tratou (XACK + XDEL), então o tamanho do stream
(XLEN) é exatamente o que falta processar. É esse número que a ingestão usa como freio.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

SPANS_STREAM = "traceflow:spans"
PROCESSORS_GROUP = "processors"


@dataclass(frozen=True)
class SpanBatch:
    project: str
    received_at_ms: int
    span_count: int
    payload: bytes  # ExportTraceServiceRequest serializado em protobuf

    def to_fields(self) -> dict[str, bytes | str | int]:
        return {
            "project": self.project,
            "received_at_ms": self.received_at_ms,
            "span_count": self.span_count,
            "payload": self.payload,
        }

    @classmethod
    def from_fields(cls, fields: Mapping[bytes, bytes]) -> SpanBatch:
        return cls(
            project=fields[b"project"].decode(),
            received_at_ms=int(fields[b"received_at_ms"]),
            span_count=int(fields[b"span_count"]),
            payload=fields[b"payload"],
        )

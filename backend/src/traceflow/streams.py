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
# Entradas que o processador não consegue ler vão para cá, com o motivo, em vez de travar a fila.
DEAD_LETTER_STREAM = "traceflow:spans:dead"

# O estado ao vivo: o processador grava o último retrato de cada projeto e ambiente numa chave
# (para quem acabou de abrir a tela) e o anuncia no canal (para quem já está olhando).
LIVE_CHANNEL = "traceflow:live"
SNAPSHOT_TTL_S = 30
# O tique sai no mesmo canal, a cada segundo, depois dos retratos, mesmo sem tráfego nenhum.
# Ele diz "o processador está no ar": sem ele, a tela não teria como separar "não chegou
# nada deste projeto" (tudo bem) de "o processamento parou" (problema).
LIVE_TICK = '{"type":"tick"}'


def snapshot_key(project_id: int, environment: str) -> str:
    return f"traceflow:snapshot:{project_id}:{environment}"


@dataclass(frozen=True)
class SpanBatch:
    project_id: int
    received_at_ms: int
    span_count: int
    payload: bytes  # ExportTraceServiceRequest serializado em protobuf

    def to_fields(self) -> dict[str, bytes | str | int]:
        return {
            "project_id": self.project_id,
            "received_at_ms": self.received_at_ms,
            "span_count": self.span_count,
            "payload": self.payload,
        }

    @classmethod
    def from_fields(cls, fields: Mapping[bytes, bytes]) -> SpanBatch:
        return cls(
            project_id=int(fields[b"project_id"]),
            received_at_ms=int(fields[b"received_at_ms"]),
            span_count=int(fields[b"span_count"]),
            payload=fields[b"payload"],
        )

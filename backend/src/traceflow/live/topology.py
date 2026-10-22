"""Quem chama quem: o catálogo de endereços aprendido pelo pareamento (capítulo 10 do guia).

Um span CLIENT sabe só o ENDEREÇO para onde a chamada foi ("payments:8000"), não o nome do
serviço que atendeu. O nome se aprende pareando: o SERVER que atendeu a chamada é filho do
CLIENT (server.parent_span_id == client.span_id). Quando os dois se encontram, o catálogo
anota "payments:8000 é o payments", e daí em diante toda chamada para esse endereço vira uma
ligação para o payments, na hora, sem esperar par nenhum.

Fora de ordem é o normal: o SERVER termina antes do CLIENT que o chamou, e cada serviço
manda os seus lotes no seu ritmo. Quem chega primeiro espera o outro numa sala de espera de
30 s. Quem nunca encontra o par (a chamada a uma API externa, que não manda spans) sai da
sala quando o prazo vence, e o endereço continua sem nome: vira um nó virtual no mapa.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from traceflow.normalize import SpanRow

PAIRING_TTL_S = 30.0

AddressKey = tuple[int, str, str]  # (projeto, ambiente, endereço)
Learned = tuple[int, str, str, str]  # (projeto, ambiente, endereço, serviço)


@dataclass(frozen=True)
class _WaitingClient:
    project_id: int
    environment: str
    address: str
    arrived: float


@dataclass(frozen=True)
class _WaitingServer:
    service: str
    arrived: float


class AddressBook:
    def __init__(self) -> None:
        self.known: dict[AddressKey, str] = {}
        # As salas de espera, pela identidade do CLIENT: (trace_id, span_id do CLIENT). Os
        # dicionários guardam a ordem de chegada, então os mais velhos ficam no começo.
        self._clients: dict[tuple[str, str], _WaitingClient] = {}
        self._servers: dict[tuple[str, str], _WaitingServer] = {}
        self.expired = 0  # metades que nunca encontraram o par (chamadas a nós virtuais, sobretudo)

    def resolve(self, project_id: int, environment: str, address: str) -> str | None:
        """O serviço que atende o endereço, ou None se ainda não se sabe (nó virtual)."""
        return self.known.get((project_id, environment, address))

    def load(self, entries: Iterable[Learned]) -> None:
        """Começa já sabendo o que foi aprendido antes (o catálogo gravado no banco).

        Sem isso, depois de um reinício, um serviço que caiu não seria mais reconhecido: ele
        não manda spans, então não há como parear de novo, e ele viraria um nó virtual.
        """
        for project_id, environment, address, service in entries:
            self.known[(project_id, environment, address)] = service

    def observe(self, rows: Iterable[SpanRow], now: float) -> list[Learned]:
        """Pareia o que chegou. Devolve os pares confirmados agora, sem repetição: quem chama
        decide o que gravar (o novo, o que mudou de serviço, o que não é gravado há tempo)."""
        paired: dict[AddressKey, str] = {}
        for row in rows:
            if row.kind == "client" and row.peer_address:
                server = self._servers.pop((row.trace_id, row.span_id), None)
                if server is None:
                    self._clients[(row.trace_id, row.span_id)] = _WaitingClient(
                        row.project_id, row.environment, row.peer_address, now
                    )
                else:
                    self._learn(row.project_id, row.environment, row.peer_address, server.service, paired)
            elif row.kind == "server" and row.parent_span_id:
                client = self._clients.pop((row.trace_id, row.parent_span_id), None)
                if client is None:
                    # pode ser o filho de um CLIENT que ainda vai chegar... ou de um span
                    # interno, que nunca chega: os dois casos esperam, e o prazo resolve
                    self._servers[(row.trace_id, row.parent_span_id)] = _WaitingServer(row.service, now)
                else:
                    self._learn(client.project_id, client.environment, client.address, row.service, paired)
        self._expire(now)
        return [(*key, service) for key, service in paired.items()]

    @property
    def waiting(self) -> int:
        return len(self._clients) + len(self._servers)

    def _learn(
        self, project_id: int, environment: str, address: str, service: str, paired: dict[AddressKey, str]
    ) -> None:
        # um endereço pode passar a apontar para outro serviço (um balanceador, um deploy
        # novo): vale o par mais recente
        key = (project_id, environment, address)
        self.known[key] = service
        paired[key] = service

    def _expire(self, now: float) -> None:
        deadline = now - PAIRING_TTL_S
        for room in (self._clients, self._servers):
            # os mais velhos estão no começo: para no primeiro que ainda está no prazo
            while room:
                oldest_key = next(iter(room))
                if room[oldest_key].arrived >= deadline:
                    break
                del room[oldest_key]
                self.expired += 1

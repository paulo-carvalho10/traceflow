"""As métricas do próprio TraceFlow, no formato do Prometheus (D23).

Cada processo (ingestão, processador, API) tem o seu registro e serve as métricas em
GET /metrics numa porta interna (`TRACEFLOW_METRICS_PORT`, 9464 no Compose), separada da
porta pública. Na publicação, o proxy repassa só a pública, e as métricas não ficam abertas.

Os contadores que já existiam para o log (os da ingestão e os do processador) não são
contados duas vezes: um coletor lê os mesmos números na hora da raspagem. Viram métricas
novas só as distribuições, que o log não tinha: atrasos e durações, em histogramas.

A raspagem roda numa linha de execução à parte. Ela só lê números, e o que for coleção
(um dicionário que o laço de eventos altera) é copiado de uma vez antes de percorrer.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable

from prometheus_client import (
    CollectorRegistry,
    Counter,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    disable_created_metrics,
    start_http_server,
)
from prometheus_client.metrics_core import Metric
from prometheus_client.registry import Collector
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("traceflow.prometheus")

# sem a série "_created" de cada contador e histograma: ela dobra as séries e não diz nada
# que o Prometheus já não saiba pelo reinício do processo
disable_created_metrics()

# segundos, de 5 ms a 1 min: o mesmo histograma serve no dia calmo e no teste de carga
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)


def new_registry() -> CollectorRegistry:
    """Um registro por processo, já com a CPU, a memória e o coletor de lixo do Python."""
    registry = CollectorRegistry()
    ProcessCollector(registry=registry)
    PlatformCollector(registry=registry)
    GCCollector(registry=registry)
    return registry


class Reading(Collector):
    """Lê, na hora da raspagem, números que o processo já mantém."""

    def __init__(self, read: Callable[[], Iterable[Metric]]) -> None:
        self._read = read

    def collect(self) -> Iterable[Metric]:
        return self._read()


class HttpMetrics:
    """As requisições HTTP de um app, contadas e cronometradas pela rota e pelo status."""

    def __init__(self, registry: CollectorRegistry, prefix: str) -> None:
        self.requests = Counter(
            f"{prefix}_requests",
            "Requisições HTTP, pela rota e pelo status",
            ["method", "route", "status"],
            registry=registry,
        )
        self.seconds = Histogram(
            f"{prefix}_request_seconds",
            "Duração das requisições HTTP, pela rota",
            ["method", "route"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        )


class RequestMetrics:
    """Middleware ASGI que alimenta o HttpMetrics.

    A rota entra pelo molde (`/api/projects/{project_id}/traces`), nunca pelo caminho de
    verdade: cada id viraria uma série nova, e o Prometheus guardaria uma por trace.
    O WebSocket fica de fora, porque uma conexão dura horas e não é uma requisição.
    """

    def __init__(self, app: ASGIApp, metrics: HttpMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500  # se o app cair antes de responder, o servidor responde 500

        async def send_and_note(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_and_note)
        finally:
            # o roteador do FastAPI deixa no scope a rota que casou; sem rota, foi um 404 ou um
            # pedido de CORS respondido antes do roteador
            route = getattr(scope.get("route"), "path", "sem rota")
            method = scope["method"]
            self.metrics.requests.labels(method, route, str(status)).inc()
            self.metrics.seconds.labels(method, route).observe(time.perf_counter() - started)


def serve(registry: CollectorRegistry, port: int | None) -> Callable[[], None]:
    """Abre o GET /metrics na porta interna, se houver uma. Devolve como fechar."""
    if port is None:
        return lambda: None
    server, thread = start_http_server(port, registry=registry)
    log.info("métricas em :%d/metrics", server.server_port)

    def close() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    return close

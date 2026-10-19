"""O que todo serviço da loja tem em comum: telemetria, cliente HTTP, caos e o jeito de chamar os outros."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from shop.chaos import Chaos, ChaosMiddleware, OutageSwitch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # uma linha por chamada afogava os logs úteis

CALL_TIMEOUT_S = float(os.environ.get("CALL_TIMEOUT_S", "2"))


def tracing_from_env(service: str) -> TracerProvider:
    """Spans vão para OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, em lotes (OTEL_BSP_SCHEDULE_DELAY).

    Sem o endpoint configurado (nos testes, por exemplo), os spans são criados e descartados.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    if os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider


def service_url(name: str) -> str:
    """Endereço de outro serviço. No Docker Compose, o nome do serviço é o nome do host."""
    return os.environ.get(f"{name.upper()}_URL", f"http://{name}:8000")


class Service:
    """Um microsserviço da loja.

    `api` é o FastAPI onde as rotas são declaradas; `asgi` é o que o uvicorn sobe
    (a api com a chave de "fora do ar" por fora).
    """

    def __init__(self, name: str, *, telemetry: bool = True, tracer_provider: TracerProvider | None = None):
        self.name = name
        self.chaos = Chaos(name, os.environ.get("CHAOS_REDIS_URL"))
        self.tracer_provider = (tracer_provider or tracing_from_env(name)) if telemetry else None
        self._http: httpx.AsyncClient | None = None
        self.api = FastAPI(title=f"shop · {name}", lifespan=self._lifespan)
        self.api.add_middleware(ChaosMiddleware, chaos=self.chaos)
        if self.tracer_provider:
            # sem os spans internos "http send"/"http receive": eram mais da metade de cada trace
            # e não dizem nada que o span SERVER já não diga
            FastAPIInstrumentor.instrument_app(
                self.api, tracer_provider=self.tracer_provider, exclude_spans=["receive", "send"]
            )
        self.asgi = OutageSwitch(self.api, self.chaos)

    @property
    def http(self) -> httpx.AsyncClient:
        """O cliente para chamar os outros serviços, criado quando o serviço sobe."""
        if self._http is None:
            raise RuntimeError(f"{self.name} ainda não subiu: o cliente HTTP nasce no lifespan")
        return self._http

    @http.setter
    def http(self, client: httpx.AsyncClient) -> None:
        self._http = client

    @asynccontextmanager
    async def _lifespan(self, _: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT_S) as client, self.chaos.polling():
            if self.tracer_provider:
                HTTPXClientInstrumentor.instrument_client(client, tracer_provider=self.tracer_provider)
            self.http = client
            yield
        if self.tracer_provider:
            self.tracer_provider.shutdown()  # envia o último lote antes de sair


async def simulate_work(mean_ms: float, jitter_ms: float) -> None:
    """Simula o trabalho do serviço (consulta ao banco, regra de negócio) com uma duração variável."""
    await asyncio.sleep(max(0.0, random.gauss(mean_ms, jitter_ms)) / 1000)


async def call(client: httpx.AsyncClient, method: str, url: str, json: Any = None) -> httpx.Response:
    """Chama outro serviço e traduz a falha dele numa resposta deste.

    - não conectou: 502; demorou demais: 504; respondeu 5xx: 502.
    - 4xx volta para quem chamou decidir (produto inexistente, pagamento recusado...).
    """
    host = httpx.URL(url).host
    try:
        response = await client.request(method, url, json=json)
    except httpx.TimeoutException as exc:
        raise HTTPException(504, f"tempo esgotado ao chamar {host}") from exc
    except httpx.TransportError as exc:
        raise HTTPException(502, f"não consegui conectar a {host}") from exc
    if response.status_code >= 500:
        raise HTTPException(502, f"{host} respondeu {response.status_code}")
    return response


def relay(response: httpx.Response) -> Any:
    """Devolve o corpo de uma resposta de sucesso ou repassa o erro 4xx com a mesma explicação."""
    if response.is_success:
        return response.json()
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    raise HTTPException(response.status_code, detail)

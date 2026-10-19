from __future__ import annotations

import httpx
import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from shop.chaos import Chaos, ChaosConfig
from shop.runtime import Service


def build(config: ChaosConfig) -> tuple[Service, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    svc = Service("teste", tracer_provider=provider)

    @svc.api.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    svc.chaos.config = config
    return svc, exporter


async def get(svc: Service, path: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=svc.asgi), base_url="http://teste") as c:
        return await c.get(path)


def server_spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    return [s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]


def test_config_le_o_hash_do_redis() -> None:
    config = ChaosConfig.parse({"latency_ms": "800", "error_rate": "0.3", "down": "1"})
    assert config == ChaosConfig(latency_ms=800, error_rate=0.3, down=True)


def test_config_invalida_vira_sem_caos_e_valores_sao_limitados() -> None:
    assert ChaosConfig.parse({"latency_ms": "muito", "error_rate": "abc"}) == ChaosConfig()
    assert ChaosConfig.parse({"error_rate": "7", "latency_ms": "-5"}) == ChaosConfig(error_rate=1.0)
    assert not ChaosConfig.parse({}).active


def test_taxa_de_erro_usa_o_sorteio() -> None:
    chaos = Chaos("x", None, rng=lambda: 0.29)
    chaos.config = ChaosConfig(error_rate=0.3)
    assert chaos.should_fail()
    chaos.rng = lambda: 0.31
    assert not chaos.should_fail()


async def test_sem_caos_a_requisicao_passa_e_gera_um_unico_span() -> None:
    svc, exporter = build(ChaosConfig())
    assert (await get(svc, "/ping")).status_code == 200
    # só o span SERVER: os internos "http send"/"http receive" estão desligados
    [span] = exporter.get_finished_spans()
    assert span.kind == SpanKind.SERVER
    assert span.status.status_code == StatusCode.UNSET


async def test_erro_injetado_aparece_no_span_como_erro() -> None:
    svc, exporter = build(ChaosConfig(error_rate=1.0))
    response = await get(svc, "/ping")
    assert response.status_code == 500
    assert "falha injetada" in response.json()["detail"]
    [span] = server_spans(exporter)
    assert span.status.status_code == StatusCode.ERROR


async def test_latencia_injetada_aparece_na_duracao_do_span() -> None:
    svc, exporter = build(ChaosConfig(latency_ms=60))
    assert (await get(svc, "/ping")).status_code == 200
    [span] = server_spans(exporter)
    assert span.end_time is not None and span.start_time is not None
    assert (span.end_time - span.start_time) / 1e6 >= 60


async def test_fora_do_ar_responde_503_sem_gerar_nenhum_span() -> None:
    svc, exporter = build(ChaosConfig(down=True))
    response = await get(svc, "/ping")
    assert response.status_code == 503
    assert exporter.get_finished_spans() == ()


@pytest.mark.parametrize("valor", ["1", "true", "sim", " TRUE "])
def test_fora_do_ar_aceita_variacoes(valor: str) -> None:
    assert ChaosConfig.parse({"down": valor}).down


async def test_sem_redis_o_polling_nao_faz_nada() -> None:
    chaos = Chaos("x", None)
    async with chaos.polling():
        assert chaos.config == ChaosConfig()

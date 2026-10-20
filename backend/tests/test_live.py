from __future__ import annotations

import json
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fakeredis import FakeAsyncRedis

from traceflow.config import Settings
from traceflow.live.aggregator import WINDOW_SECONDS, LiveAggregator
from traceflow.live.histogram import BUCKETS, Histogram, bucket_of
from traceflow.normalize import SpanRow
from traceflow.processor.app import Processor
from traceflow.streams import LIVE_CHANNEL, snapshot_key

NOW = 1_760_000_000.0  # um instante qualquer, em segundos


def exact_quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(q * len(ordered) + 0.999999) - 1))]


# ---------- histograma ----------


def test_sao_73_baldes_de_0_1_ms_a_60_s() -> None:
    assert BUCKETS == 73
    assert bucket_of(0.01) == 0 and bucket_of(10**9) == BUCKETS - 1
    assert bucket_of(1.0) < bucket_of(1.3) < bucket_of(100)


@pytest.mark.parametrize("q", [0.5, 0.95, 0.99])
def test_percentil_do_histograma_erra_menos_de_10_por_cento(q: float) -> None:
    rng = random.Random(42)
    # mistura parecida com a da loja: muita coisa rápida e uma cauda lenta
    values = [rng.lognormvariate(3, 0.6) for _ in range(9000)] + [rng.uniform(500, 3000) for _ in range(1000)]
    estimate = Histogram.of(values).quantile(q)
    assert estimate is not None
    exact = exact_quantile(values, q)
    assert abs(estimate - exact) / exact < 0.10


def test_histogramas_somados_dao_o_mesmo_percentil_da_janela_inteira() -> None:
    rng = random.Random(7)
    seconds = [[rng.expovariate(1 / 50) for _ in range(200)] for _ in range(10)]
    merged = Histogram()
    for values in seconds:
        merged.merge(Histogram.of(values))
    whole = Histogram.of([v for values in seconds for v in values])
    assert merged.counts == whole.counts and merged.quantile(0.95) == whole.quantile(0.95)


def test_media_de_percentis_nao_e_percentil() -> None:
    # o exemplo do capítulo 6: um segundo rápido e cheio, outro lento e vazio
    rapido = [50.0] * 990
    lento = [2000.0] * 10
    media_dos_p95 = (Histogram.of(rapido).quantile(0.95) + Histogram.of(lento).quantile(0.95)) / 2  # type: ignore[operator]
    verdadeiro = Histogram.of(rapido + lento).quantile(0.95)
    assert verdadeiro is not None and verdadeiro < 60  # 99% das requisições foram rápidas
    assert media_dos_p95 > 900  # a média dos p95 diria quase 1 s


def test_histograma_vazio_nao_tem_percentil() -> None:
    assert Histogram().quantile(0.95) is None


# ---------- agregador ----------


def span(service: str, ended_at: float, ms: float = 20, *, root: bool = False, error: bool = False,
         kind: str = "server", env: str = "demo", project: int = 1) -> SpanRow:  # fmt: skip
    start = datetime.fromtimestamp(ended_at - ms / 1000, tz=UTC)
    return SpanRow(
        project_id=project, environment=env, trace_id="a" * 32, span_id="b" * 16,
        parent_span_id=None if root else "c" * 16, service=service, name="x", kind=kind,
        start_time=start, duration_ms=ms, status="error" if error else "unset", status_message=None,
        http_method=None, http_route=None, http_status_code=None, peer_address=None,
        attributes={}, resource={}, events=[],
    )  # fmt: skip


def test_janela_de_10_s_que_termina_3_s_atras() -> None:
    agg = LiveAggregator()
    # 5 req/s no gateway (raiz) durante os últimos 20 s, 1 em cada 5 com erro
    rows = [
        span("gateway", NOW - s - 0.5, root=True, error=(i == 0))
        for s in range(20)
        for i in range(5)
    ]  # fmt: skip
    agg.add(rows, NOW)
    [snap] = agg.snapshots(NOW).values()
    entry, [gateway] = snap["entry"], snap["services"]
    assert gateway["rps"] == 5.0 and gateway["requests"] == 5 * WINDOW_SECONDS
    assert gateway["error_rate"] == pytest.approx(0.2) and gateway["availability"] == pytest.approx(0.8)
    assert entry["rps"] == 5.0  # o gateway é a porta de entrada: a linha "entrada" bate com ele
    assert snap["window"]["to"] == int(NOW) - 3


def test_o_segundo_atual_nao_entra_na_janela() -> None:
    agg = LiveAggregator()
    agg.add([span("gateway", NOW - 0.2) for _ in range(100)], NOW)  # tudo no segundo que está acontecendo
    [snap] = agg.snapshots(NOW).values()
    assert snap["services"][0]["requests"] == 0  # ainda incompleto: aparece daqui a 3 s


def test_entrada_conta_cada_requisicao_uma_vez_so() -> None:
    agg = LiveAggregator()
    compra = [span("gateway", NOW - 5, root=True), span("orders", NOW - 5), span("payments", NOW - 5)]
    agg.add(compra * 10, NOW)
    [snap] = agg.snapshots(NOW).values()
    assert snap["entry"]["requests"] == 10  # dez compras
    assert sum(s["requests"] for s in snap["services"]) == 30  # somar serviços contaria três vezes


def test_spans_client_nao_contam_no_red_do_servico() -> None:
    agg = LiveAggregator()
    agg.add([span("orders", NOW - 5, kind="client")], NOW)
    assert agg.snapshots(NOW) == {}


def test_span_atrasado_cai_no_segundo_certo_e_muito_atrasado_e_descartado() -> None:
    agg = LiveAggregator()
    agg.add([span("gateway", NOW - 8)], NOW - 7)  # chegou cedo
    agg.add([span("gateway", NOW - 8)], NOW)  # o mesmo segundo, chegando 7 s depois: soma no mesmo balde
    agg.add([span("gateway", NOW - 120)], NOW)  # fora da roda de 60 s
    [snap] = agg.snapshots(NOW).values()
    assert snap["services"][0]["requests"] == 2 and agg.late == 1


def test_projetos_e_ambientes_tem_retratos_separados_e_servico_parado_some() -> None:
    agg = LiveAggregator()
    agg.add([span("api", NOW - 5, project=1, env="demo"), span("api", NOW - 5, project=2, env="prod")], NOW)
    assert set(agg.snapshots(NOW)) == {(1, "demo"), (2, "prod")}
    assert agg.snapshots(NOW + 120) == {}  # dois minutos sem nada: some


def test_serie_de_60_s_para_os_graficos() -> None:
    agg = LiveAggregator()
    agg.add([span("gateway", NOW - 10.5), span("gateway", NOW - 10.5, ms=300)], NOW)
    [snap] = agg.snapshots(NOW).values()
    series = snap["services"][0]["series"]
    assert len(series) == 57  # de 60 s atrás até a marca d'água
    point = next(p for p in series if p["t"] == int(NOW - 10.5))
    assert point["rps"] == 2 and point["p95_ms"] is not None and point["p95_ms"] > 200


def test_p95_da_serie_desliza_e_bate_com_a_conta_direta() -> None:
    # A janela deslizante soma o segundo que entra e subtrai o que sai. Este teste refaz a
    # conta do zero para cada ponto (os 10 s até ele) e exige o mesmo resultado em todos.
    random.seed(7)
    agg = LiveAggregator()
    ended: dict[int, list[float]] = {}
    rows = []
    for s in range(4, 59):
        for _ in range(random.randint(0, 8)):  # inclusive segundos vazios
            ms = random.lognormvariate(3, 1)
            rows.append(span("gateway", NOW - s - 0.5, ms=ms))
            ended.setdefault(int(NOW - s - 0.5), []).append(ms)
    agg.add(rows, NOW)
    [snap] = agg.snapshots(NOW).values()
    for point in snap["services"][0]["series"]:
        window = [
            ms for s in range(point["t"] - WINDOW_SECONDS + 1, point["t"] + 1) for ms in ended.get(s, [])
        ]
        assert point["p95_ms"] == Histogram.of(window).quantile(0.95), point["t"]


# ---------- publicação ----------


@pytest.fixture
async def fake_redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    yield client
    await client.aclose()


async def test_processador_grava_e_anuncia_o_retrato(fake_redis: FakeAsyncRedis) -> None:
    p = Processor(fake_redis, None, Settings(), clock_ns=lambda: int(NOW * 1e9))  # type: ignore[arg-type]
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(LIVE_CHANNEL)
    p.live.add([span("gateway", NOW - 5, root=True)], NOW)
    assert await p.publish_live() == 1
    raw = await fake_redis.get(snapshot_key(1, "demo"))
    assert raw is not None
    stored = json.loads(raw)
    assert stored["services"][0]["name"] == "gateway"
    assert 0 < await fake_redis.ttl(snapshot_key(1, "demo")) <= 30  # retrato velho some sozinho
    message = None
    for _ in range(5):
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if message:
            break
    assert message is not None and json.loads(message["data"])["project_id"] == 1
    await pubsub.aclose()


def test_tempo_do_evento_usa_o_fim_do_span() -> None:
    # começou 2 s antes do fim da janela e durou 2,5 s: terminou depois da marca d'água
    agg = LiveAggregator()
    ended = NOW - 2
    agg.add([span("gateway", ended, ms=2500)], NOW)
    [snap] = agg.snapshots(NOW).values()
    assert snap["services"][0]["requests"] == 0
    assert datetime.fromtimestamp(ended, tz=UTC) - timedelta(milliseconds=2500) < datetime.fromtimestamp(
        NOW, tz=UTC
    )

"""O mapa ao vivo: o pareamento CLIENT/SERVER, as ligações no retrato e o "sem resposta"."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fakeredis import FakeAsyncRedis
from test_processor import FakeStore

from traceflow.config import Settings
from traceflow.live.aggregator import NO_RESPONSE_MIN_CALLS, LiveAggregator, call_failed
from traceflow.live.topology import PAIRING_TTL_S, AddressBook
from traceflow.normalize import SpanRow
from traceflow.processor.app import Processor
from traceflow.streams import snapshot_key

NOW = 1_760_000_000.0


def span(kind: str, service: str, span_id: str, parent: str | None = None, *, trace: str = "t" * 32,
         ended_at: float = NOW - 5, ms: float = 20, peer: str | None = None, code: int | None = 200,
         status: str = "unset", project: int = 1, env: str = "demo") -> SpanRow:  # fmt: skip
    return SpanRow(
        project_id=project, environment=env, trace_id=trace, span_id=span_id.ljust(16, "0"),
        parent_span_id=parent.ljust(16, "0") if parent else None, service=service, name="x", kind=kind,
        start_time=datetime.fromtimestamp(ended_at - ms / 1000, tz=UTC), duration_ms=ms, status=status,
        status_message=None, http_method="POST", http_route=None, http_status_code=code, peer_address=peer,
        attributes={}, resource={}, events=[],
    )  # fmt: skip


def call(caller: str, address: str, span_id: str, **kw: object) -> SpanRow:
    return span("client", caller, span_id, "e1", peer=address, **kw)  # type: ignore[arg-type]


def served(service: str, span_id: str, client_span: str, **kw: object) -> SpanRow:
    return span("server", service, span_id, client_span, **kw)  # type: ignore[arg-type]


# ---------- o catálogo de endereços (pareamento) ----------


def test_aprende_o_nome_nas_duas_ordens_de_chegada() -> None:
    book = AddressBook()
    # o SERVER chega antes do CLIENT (o normal: ele termina primeiro)
    assert book.observe([served("payments", "s1", "c1")], NOW) == []
    assert book.observe([call("orders", "payments:8000", "c1")], NOW + 0.4) == [
        (1, "demo", "payments:8000", "payments")
    ]
    # o CLIENT chega antes, no mesmo lote do SERVER
    learned = book.observe([call("gateway", "orders:8000", "c2"), served("orders", "s2", "c2")], NOW + 1)
    assert learned == [(1, "demo", "orders:8000", "orders")]
    assert book.resolve(1, "demo", "orders:8000") == "orders" and book.waiting == 0


def test_endereco_que_nunca_pareia_fica_sem_nome_e_sai_da_sala_no_prazo() -> None:
    book = AddressBook()
    book.observe([call("payments", "bank:8000", "c1")], NOW)  # o banco não manda spans
    book.observe([], NOW + PAIRING_TTL_S - 1)
    assert book.waiting == 1
    book.observe([], NOW + PAIRING_TTL_S + 1)
    assert book.waiting == 0 and book.expired == 1
    assert book.resolve(1, "demo", "bank:8000") is None  # vira um nó virtual


def test_o_mesmo_endereco_em_outro_projeto_e_outra_coisa() -> None:
    book = AddressBook()
    book.observe([call("orders", "api:80", "c1"), served("payments", "s1", "c1")], NOW)
    assert book.resolve(1, "demo", "api:80") == "payments"
    assert book.resolve(2, "demo", "api:80") is None and book.resolve(1, "prod", "api:80") is None


def test_endereco_que_passa_a_apontar_para_outro_servico_troca_de_dono() -> None:
    book = AddressBook()
    book.observe([call("orders", "api:80", "c1"), served("payments", "s1", "c1")], NOW)
    learned = book.observe([call("orders", "api:80", "c2"), served("payments-v2", "s2", "c2")], NOW + 1)
    assert (
        learned == [(1, "demo", "api:80", "payments-v2")]
        and book.resolve(1, "demo", "api:80") == "payments-v2"
    )


def test_o_lote_devolve_cada_par_uma_vez_so() -> None:
    book = AddressBook()
    rows = [
        r
        for i in range(5)
        for r in (call("orders", "payments:8000", f"c{i}"), served("payments", f"s{i}", f"c{i}"))
    ]
    assert book.observe(rows, NOW) == [(1, "demo", "payments:8000", "payments")]


def test_comeca_sabendo_o_que_estava_gravado() -> None:
    book = AddressBook()
    book.load([(1, "demo", "notifications:8000", "notifications")])
    assert book.resolve(1, "demo", "notifications:8000") == "notifications"


# ---------- o que conta como falha numa ligação (D49) ----------


@pytest.mark.parametrize(
    ("code", "status", "failed"),
    [
        (200, "unset", False),
        (402, "error", False),  # cartão recusado: resposta legítima, o OpenTelemetry marca erro no CLIENT
        (404, "error", False),
        (503, "error", True),
        (None, "error", True),  # sem resposta: conexão recusada, tempo esgotado
    ],
)
def test_falha_e_5xx_ou_sem_resposta(code: int | None, status: str, failed: bool) -> None:
    assert call_failed(call("orders", "payments:8000", "c1", code=code, status=status)) is failed


# ---------- as ligações no retrato ----------


def test_retrato_traz_as_ligacoes_com_o_nome_aprendido_e_os_nos_virtuais() -> None:
    agg, book = LiveAggregator(), AddressBook()
    rows = [span("server", "gateway", "g1", None)]  # entrou pelo gateway
    for i in range(10):
        rows += [call("gateway", "orders:8000", f"c{i}"), served("orders", f"o{i}", f"c{i}")]
        rows += [
            call(
                "orders",
                "bank:443",
                f"b{i}",
                code=402 if i < 3 else 200,
                status="error" if i < 3 else "unset",
            )
        ]
    agg.add(rows, NOW)
    book.observe(rows, NOW)
    [snap] = agg.snapshots(NOW, book.resolve).values()
    edges = {(e["source"], e["target"]): e for e in snap["edges"]}
    assert edges[("gateway", "orders")]["virtual"] is False and edges[("gateway", "orders")]["requests"] == 10
    bank = edges[("orders", "bank:443")]
    assert bank["virtual"] is True and bank["error_rate"] == 0  # 402 não é falha
    gateway = next(s for s in snap["services"] if s["name"] == "gateway")
    assert gateway["entry_rps"] == pytest.approx(0.1)  # 1 requisição entrou por ele em 10 s
    assert snap["unresponsive"] == []


def test_servico_que_caiu_fica_sem_resposta() -> None:
    agg, book = LiveAggregator(), AddressBook()
    book.load([(1, "demo", "notifications:8000", "notifications")])  # aprendido antes de cair
    falhas = [
        call("orders", "notifications:8000", f"c{i}", code=503, status="error")
        for i in range(NO_RESPONSE_MIN_CALLS)
    ]
    agg.add(falhas, NOW)
    [snap] = agg.snapshots(NOW, book.resolve).values()
    assert snap["unresponsive"] == ["notifications"]
    assert snap["edges"][0]["target"] == "notifications" and snap["edges"][0]["error_rate"] == 1.0


def test_sem_resposta_exige_chamadas_suficientes_e_nenhum_atendimento() -> None:
    book = AddressBook()
    book.load([(1, "demo", "payments:8000", "payments")])
    poucas = LiveAggregator()
    poucas.add(
        [
            call("orders", "payments:8000", f"c{i}", code=503, status="error")
            for i in range(NO_RESPONSE_MIN_CALLS - 1)
        ],
        NOW,
    )
    assert next(iter(poucas.snapshots(NOW, book.resolve).values()))["unresponsive"] == []
    atendendo = LiveAggregator()  # falha, mas atende: está doente (Etapa 8), não caído
    atendendo.add(
        [call("orders", "payments:8000", f"c{i}", code=503, status="error") for i in range(10)], NOW
    )
    atendendo.add([served("payments", "s1", "c1", status="error", code=500)], NOW)
    assert next(iter(atendendo.snapshots(NOW, book.resolve).values()))["unresponsive"] == []


# ---------- o processador ----------


@pytest.fixture
async def fake_redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis()
    yield client
    await client.aclose()


async def test_processador_grava_o_catalogo_so_o_que_e_novo_ou_mudou(fake_redis: FakeAsyncRedis) -> None:
    store = FakeStore()
    p = Processor(fake_redis, store, Settings(), clock_ns=lambda: int(NOW * 1e9))
    when = datetime.fromtimestamp(NOW, tz=UTC)
    await p.update_addresses([(1, "demo", "payments:8000", "payments")], when)
    await p.update_addresses([(1, "demo", "payments:8000", "payments")], when)  # o mesmo, logo depois
    assert len(store.addresses) == 1
    await p.update_addresses([(1, "demo", "payments:8000", "payments-v2")], when)  # mudou: grava já
    assert [a[3] for a in store.addresses] == ["payments", "payments-v2"]


async def test_processador_sobe_com_o_catalogo_e_o_retrato_ja_sai_com_os_nomes(
    fake_redis: FakeAsyncRedis,
) -> None:
    store = FakeStore()
    store.preloaded = [(1, "demo", "notifications:8000", "notifications")]
    p = Processor(fake_redis, store, Settings(), clock_ns=lambda: int(NOW * 1e9))
    await p.load_addresses()
    p.live.add([call("orders", "notifications:8000", "c1")], NOW)
    await p.publish_live()
    raw = await fake_redis.get(snapshot_key(1, "demo"))
    assert raw is not None
    [edge] = json.loads(raw)["edges"]
    assert (edge["source"], edge["target"], edge["virtual"]) == ("orders", "notifications", False)

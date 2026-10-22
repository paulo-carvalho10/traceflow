"""Incidentes: regras, histerese, linha de base, causa provável, impacto, severidade e ciclo de vida."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import pytest

from traceflow.incidents.analysis import Call, Endpoint, Node, analyze, strongly_connected
from traceflow.incidents.engine import Assessor, node_stats
from traceflow.incidents.health import BASELINE_MIN_SAMPLES, HYSTERESIS, NodeHealth
from traceflow.incidents.rules import DEFAULT_RULES, HEALTHY, NodeStats, Rule, Verdict, evaluate
from traceflow.incidents.text import reason
from traceflow.incidents.tracker import RESOLVE_AFTER_S, IncidentTracker
from traceflow.live.aggregator import LiveAggregator
from traceflow.normalize import SpanRow


def stats(requests: int = 100, error_rate: float = 0.0, p95: float | None = 50.0) -> NodeStats:
    return NodeStats(requests, error_rate, p95, p95, requests / 10)


# ---------- regras ----------


def test_regras_padrao_degradado_a_partir_de_5_e_falhando_a_partir_de_25() -> None:
    assert evaluate("payments", stats(error_rate=0.04), DEFAULT_RULES, None).state == "healthy"
    assert evaluate("payments", stats(error_rate=0.05), DEFAULT_RULES, None).state == "degraded"
    verdict = evaluate("payments", stats(error_rate=0.30), DEFAULT_RULES, None)
    assert verdict.state == "failing" and reason(verdict) == "erro 30% (regra: erro ≥ 25%)"


def test_com_pouco_trafego_a_regra_nao_dispara() -> None:
    assert evaluate("payments", stats(requests=3, error_rate=0.33), DEFAULT_RULES, None).state == "healthy"


def test_regra_relativa_espera_a_linha_de_base_e_exige_50_ms_a_mais() -> None:
    slow = stats(p95=1600)
    assert evaluate("bank", slow, DEFAULT_RULES, None).state == "healthy"  # ainda aprendendo o normal
    verdict = evaluate("bank", slow, DEFAULT_RULES, 100.0)
    assert verdict.state == "degraded"
    assert reason(verdict) == "p95 1,6 s, 16,0× a linha de base (100 ms)"  # noqa: RUF001
    # dobrou, mas de 4 para 9 ms: ninguém sente
    assert evaluate("cache", stats(p95=9), DEFAULT_RULES, 4.0).state == "healthy"


def test_regra_de_um_servico_so_e_regra_de_disponibilidade() -> None:
    rules = [Rule("orders", "availability", "<=", 0.99, "failing")]
    assert evaluate("orders", stats(error_rate=0.02), rules, None).state == "failing"
    assert evaluate("payments", stats(error_rate=0.02), rules, None).state == "healthy"


# ---------- histerese e linha de base ----------


def test_estado_so_muda_depois_de_3_retratos_seguidos() -> None:
    node = NodeHealth()
    bad = Verdict("failing")
    assert [node.observe(bad, t, 50, 100) for t in range(HYSTERESIS)] == [False, False, True]
    assert node.state == "failing" and node.since == HYSTERESIS - 1
    node.observe(HEALTHY, 10, 50, 100)  # um segundo bom no meio da falha não fecha nada
    node.observe(bad, 11, 50, 100)
    assert node.state == "failing"


def test_oscilando_entre_degradado_e_falhando_ainda_adoece() -> None:
    node = NodeHealth()
    for t, state in enumerate(["degraded", "failing", "degraded"]):
        node.observe(Verdict(state), t, 50, 100)  # type: ignore[arg-type]
    assert node.state == "degraded"  # o último pedido vale


def test_linha_de_base_so_aprende_com_o_no_saudavel() -> None:
    node = NodeHealth()
    for t in range(BASELINE_MIN_SAMPLES - 1):
        node.observe(HEALTHY, t, 100, 100)
    assert node.baseline.ready is None  # 29 segundos: ainda não vale
    node.observe(HEALTHY, 99, 100, 100)
    assert node.baseline.ready == pytest.approx(100)
    for t in range(100, 110):  # adoece por latência: a lentidão não pode virar o novo normal
        node.observe(Verdict("degraded"), t, 1600, 100)
    assert node.baseline.ready == pytest.approx(100, rel=0.05)


# ---------- causa provável, impacto e severidade ----------


def test_tarjan_agrupa_ciclos() -> None:
    components = strongly_connected(["a", "b", "c", "d"], {"a": ["b"], "b": ["a", "c"], "c": ["d"]})
    assert sorted(components) == [["a", "b"], ["c"], ["d"]]


def test_tarjan_aguenta_uma_cadeia_longa_sem_recursao() -> None:
    names = [f"s{i:04d}" for i in range(5000)]
    edges = {a: [b] for a, b in pairwise(names)}
    assert len(strongly_connected(names, edges)) == 5000


SHOP = [
    Call("gateway", "orders"),
    Call("gateway", "inventory"),
    Call("orders", "payments"),
    Call("orders", "notifications"),
    Call("payments", "bank:8000"),
]
CHECKOUT = Endpoint(
    "POST /checkout",
    "gateway",
    frozenset({"gateway", "orders", "payments", "notifications", "bank:8000"}),
    6,
    0.0,
    120,
    60,
    120,
)
PRODUCTS = Endpoint("GET /products", "gateway", frozenset({"gateway", "inventory"}), 14, 0.0, 20, 140, 20)


def sick(**states: tuple[str, float]) -> dict[str, Node]:
    """Nós doentes por erro: nome=(estado, taxa de erro); os outros da loja, saudáveis."""
    nodes = {
        n: Node(n, "healthy")
        for n in ("gateway", "orders", "inventory", "payments", "notifications", "bank:8000")
    }
    for name, (state, error) in states.items():
        nodes[name] = Node(name, state, error_rate=error, sick_by="errors")  # type: ignore[arg-type]
    return nodes


def test_erro_que_sobe_pela_cadeia_aponta_o_payments() -> None:
    nodes = sick(payments=("failing", 0.30), orders=("failing", 0.28), gateway=("degraded", 0.08))
    calls = [Call("gateway", "orders", 0.28), Call("orders", "payments", 0.30), *SHOP[1:2], *SHOP[3:]]
    checkout = Endpoint(**{**CHECKOUT.__dict__, "error_rate": 0.28})
    result = analyze(nodes, calls, [checkout, PRODUCTS])
    assert [c.node for c in result.causes] == ["payments"]
    assert result.affected == ["gateway", "orders"]  # doentes por causa dele
    assert [e.route for e in result.endpoints] == ["POST /checkout"]  # o GET /products não passa por ele
    assert result.severity == "SEV1"  # 28% de erro numa rota de entrada


def test_quem_piora_alem_da_dependencia_tambem_e_causa() -> None:
    # o orders com 30% de erro, mas a ligação com o payments só tem 6%: ele tem problema próprio
    nodes = sick(payments=("degraded", 0.06), orders=("failing", 0.30))
    calls = [Call("orders", "payments", 0.06), Call("gateway", "orders", 0.30)]
    result = analyze(nodes, calls, [])
    assert [(c.node, c.own) for c in result.causes] == [("orders", True), ("payments", False)]


def test_latencia_do_banco_externo_aponta_o_banco() -> None:
    nodes = {
        "payments": Node("payments", "degraded", p95_ms=1650, baseline_ms=110, sick_by="latency"),
        "bank:8000": Node("bank:8000", "degraded", p95_ms=1590, baseline_ms=95, sick_by="latency"),
        "orders": Node("orders", "degraded", p95_ms=1700, baseline_ms=160, sick_by="latency"),
    }
    slow = Endpoint(**{**CHECKOUT.__dict__, "p95_ms": 1750.0})
    result = analyze(nodes, SHOP, [slow, PRODUCTS])
    assert [c.node for c in result.causes] == ["bank:8000"]
    assert result.severity == "SEV2"  # o checkout ficou 14x mais lento, sem erro


def test_dependencia_nao_critica_caida_e_sev3() -> None:
    nodes = sick()
    nodes["notifications"] = Node("notifications", "unresponsive", sick_by="unresponsive")
    result = analyze(nodes, SHOP, [CHECKOUT, PRODUCTS])
    assert [c.node for c in result.causes] == ["notifications"]
    assert result.at_risk == ["gateway", "orders"]  # dependem dele, mas seguem bem
    assert result.severity == "SEV3"  # as compras continuam: quem usa não sente


def test_estoque_caido_derruba_a_vitrine_e_e_sev1() -> None:
    nodes = sick(gateway=("failing", 0.7))
    nodes["inventory"] = Node("inventory", "unresponsive", sick_by="unresponsive")
    products = Endpoint(**{**PRODUCTS.__dict__, "error_rate": 1.0})
    calls = [Call("gateway", "inventory", 1.0) if c.target == "inventory" else c for c in SHOP]
    result = analyze(nodes, calls, [CHECKOUT, products])
    assert [c.node for c in result.causes] == ["inventory"] and result.severity == "SEV1"


def test_ciclo_doente_aponta_o_grupo_inteiro() -> None:
    nodes = {"a": Node("a", "failing", sick_by="errors"), "b": Node("b", "failing", sick_by="errors")}
    result = analyze(nodes, [Call("a", "b"), Call("b", "a")], [])
    assert sorted(c.node for c in result.causes) == ["a", "b"]


# ---------- o motor: do retrato ao estado ----------


def snapshot(payments_error: float = 0.0, bank_p95: float = 95.0) -> dict[str, Any]:
    def svc(name: str, error: float = 0.0, p95: float = 50.0) -> dict[str, Any]:
        return {"name": name, "requests": 60, "error_rate": error, "p95_ms": p95, "p99_ms": p95, "rps": 6.0}

    return {
        "project_id": 1,
        "environment": "demo",
        "services": [svc("gateway"), svc("orders", payments_error), svc("payments", payments_error)],
        "edges": [
            {
                "source": "orders",
                "target": "payments",
                "error_rate": payments_error,
                "virtual": False,
                "requests": 60,
                "rps": 6.0,
                "p95_ms": 50.0,
            },
            {
                "source": "payments",
                "target": "bank:8000",
                "error_rate": 0.0,
                "virtual": True,
                "requests": 60,
                "rps": 6.0,
                "p95_ms": bank_p95,
            },
        ],
        "unresponsive": [],
        "entrypoints": [
            {
                "route": "POST /checkout",
                "service": "gateway",
                "rps": 6.0,
                "error_rate": payments_error,
                "p95_ms": 120.0,
                "requests": 60,
                "nodes": ["gateway", "orders", "payments", "bank:8000"],
            }
        ],
    }


def test_no_externo_herda_a_saude_das_ligacoes() -> None:
    stats_by_node, virtual = node_stats(snapshot(bank_p95=1500))
    assert virtual == {"bank:8000"} and stats_by_node["bank:8000"].p95_ms == 1500


def test_motor_adoece_depois_da_histerese_e_aponta_a_causa() -> None:
    assessor = Assessor()
    results = [
        assessor.assess(snapshot(payments_error=0.3), list(DEFAULT_RULES), t) for t in range(HYSTERESIS)
    ]
    assert [r.sick for r in results] == [False, False, True]
    last = results[-1]
    assert last.verdicts["payments"].state == "failing"
    assert [c.node for c in last.analysis.causes] == ["payments"] and last.analysis.severity == "SEV1"
    assert ("payments", "healthy", "failing") in last.changes


# ---------- o ciclo de vida ----------


def test_incidente_abre_conta_a_historia_e_resolve_depois_de_30_s_saudavel() -> None:
    assessor, tracker = Assessor(), IncidentTracker()
    channel = (1, "demo")
    incident = None
    for t in range(HYSTERESIS):
        incident = tracker.step(
            channel, assessor.assess(snapshot(payments_error=0.3), list(DEFAULT_RULES), t), t
        )
    assert incident is not None and incident.status == "open"
    assert incident.title == "payments falhando" and incident.severity == "SEV1"
    kinds = [e.kind for e in incident.pending]
    assert kinds[0] == "opened" and "node_state" in kinds
    assert incident.public()["causes"][0]["reason"] == "erro 30% (regra: erro ≥ 25%)"

    t = HYSTERESIS
    while tracker.open:  # a falha acaba: precisa ficar saudável por 30 s
        incident = tracker.step(channel, assessor.assess(snapshot(), list(DEFAULT_RULES), t), t)
        t += 1
    assert incident is not None and incident.status == "resolved"
    assert RESOLVE_AFTER_S <= t - HYSTERESIS <= RESOLVE_AFTER_S + HYSTERESIS + 2
    assert [e.kind for e in incident.pending][-1] == "resolved"
    assert any("payments: falhando → saudável" in e.message for e in incident.pending)


def test_titulo_fica_com_o_pior_estado_mesmo_na_recuperacao_gradual() -> None:
    assessor, tracker = Assessor(), IncidentTracker()
    incident = None
    for t, error in enumerate([0.3] * 4 + [0.1] * 5):  # falhando, e depois só degradado
        incident = tracker.step((1, "demo"), assessor.assess(snapshot(error), list(DEFAULT_RULES), t), t)
    assert incident is not None
    assert incident.causes[0]["state"] == "degraded"  # o agora
    assert incident.title == "payments falhando"  # o pior que chegou


def test_falha_que_volta_antes_de_30_s_e_o_mesmo_incidente() -> None:
    assessor, tracker = Assessor(), IncidentTracker()
    timeline = [0.3] * 5 + [0.0] * 10 + [0.3] * 5
    ids = set()
    for t, error in enumerate(timeline):
        incident = tracker.step((1, "demo"), assessor.assess(snapshot(error), list(DEFAULT_RULES), t), t)
        if incident:
            ids.add(incident.id)
    assert len(ids) == 1


def test_gravado_sai_da_fila_e_incidente_retomado_continua_com_o_mesmo_id() -> None:
    assessor, tracker = Assessor(), IncidentTracker()
    incident = None
    for t in range(HYSTERESIS):
        incident = tracker.step((1, "demo"), assessor.assess(snapshot(0.3), list(DEFAULT_RULES), t), t)
    assert incident is not None and incident.id in tracker.unsaved
    tracker.saved(incident, list(incident.pending))
    assert incident.id not in tracker.unsaved and not incident.dirty

    restarted = IncidentTracker()  # o processador reiniciou: o incidente aberto volta do banco
    restarted.resume([incident])
    again = restarted.step((1, "demo"), Assessor().assess(snapshot(0.3), list(DEFAULT_RULES), 100), 100)
    assert again is not None and again.id == incident.id


# ---------- as rotas de entrada ----------


def span(
    kind: str,
    service: str,
    span_id: str,
    parent: str | None,
    *,
    route: str | None = None,
    peer: str | None = None,
    ended: float = 1_760_000_000 - 5,
) -> SpanRow:
    return SpanRow(
        project_id=1,
        environment="demo",
        trace_id="t" * 32,
        span_id=span_id.ljust(16, "0"),
        parent_span_id=parent.ljust(16, "0") if parent else None,
        service=service,
        name="x",
        kind=kind,
        start_time=datetime.fromtimestamp(ended - 0.02, tz=UTC),
        duration_ms=20,
        status="unset",
        status_message=None,
        http_method="POST" if route else None,
        http_route=route,
        http_status_code=200,
        peer_address=peer,
        attributes={},
        resource={},
        events=[],
    )


def test_rota_de_entrada_sabe_por_onde_passou_mesmo_com_a_raiz_chegando_por_ultimo() -> None:
    now = 1_760_000_000.0
    agg = LiveAggregator()
    agg.add(
        [span("server", "payments", "p1", "c2"), span("client", "payments", "c3", "p1", peer="bank:8000")],
        now,
    )
    agg.add(
        [span("server", "orders", "o1", "c1"), span("client", "orders", "c2", "o1", peer="payments:8000")],
        now,
    )
    agg.add([span("server", "gateway", "g1", None, route="/checkout")], now)  # a raiz termina por último
    agg.add([span("client", "gateway", "c9", "g1", peer="late:8000")], now)  # chegou atrasado: entra direto
    [snap] = agg.snapshots(now, lambda p, e, a: {"payments:8000": "payments"}.get(a)).values()
    [route] = snap["entrypoints"]
    assert route["route"] == "POST /checkout" and route["service"] == "gateway" and route["requests"] == 1
    assert route["nodes"] == ["bank:8000", "gateway", "late:8000", "orders", "payments"]


# ---------- o processador com o motor ligado ----------


async def test_processador_abre_o_incidente_no_retrato_e_grava_repetindo_se_o_banco_falhar() -> None:
    import json

    from fakeredis import FakeAsyncRedis
    from test_processor import FakeStore

    from traceflow.config import Settings
    from traceflow.processor.app import Processor
    from traceflow.streams import snapshot_key

    redis, store, clock = FakeAsyncRedis(), FakeStore(), [1_760_000_000.0]
    p = Processor(redis, store, Settings(), clock_ns=lambda: int(clock[0] * 1e9))
    p.live.snapshots = lambda now, resolve=None: {(1, "demo"): snapshot(payments_error=0.3)}  # type: ignore[method-assign]
    store.rules = [  # as regras padrão, como viriam da tabela alert_rules
        {"id": i, "project_id": 1, **{k: getattr(r, k) for k in
         ("target", "metric", "operator", "threshold", "state", "relative", "min_requests")}}
        for i, r in enumerate(DEFAULT_RULES)
    ]  # fmt: skip
    store.failures = 1  # a primeira gravação do incidente falha
    for _ in range(HYSTERESIS):
        await p.publish_live()
        clock[0] += 1
    raw = await redis.get(snapshot_key(1, "demo"))
    assert raw is not None
    live = json.loads(raw)
    assert live["incident"]["title"] == "payments falhando" and live["incident"]["severity"] == "SEV1"
    assert live["health"]["payments"]["state"] == "failing"
    assert store.incidents == {}  # o banco falhou: ficou para o próximo segundo
    await p.publish_live()
    [row] = store.incidents.values()
    assert row["id"] == live["incident"]["id"] and row["status"] == "open"
    assert store.events[0]["kind"] == "opened"
    await redis.aclose()


def test_servico_que_caiu_e_apontado_pelo_lado_de_quem_chama_antes_do_sem_resposta() -> None:
    # O inventory caiu atrás do balanceador: não manda span nenhum, mas as chamadas para ele
    # falham 100%. Antes desta regra, a causa saía "orders" até a janela esvaziar (~17 s).
    def down(t: int) -> dict[str, Any]:
        snap = snapshot()
        snap["services"] = [
            {"name": n, "requests": 60, "error_rate": e, "p95_ms": 50.0, "p99_ms": 50.0, "rps": 6.0}
            for n, e in (("gateway", 0.7), ("orders", 0.3))
        ]
        snap["edges"] = [
            {"source": "gateway", "target": "inventory", "error_rate": 1.0, "virtual": False,
             "requests": 140, "rps": 14.0, "p95_ms": 2.0},
            {"source": "gateway", "target": "orders", "error_rate": 0.3, "virtual": False,
             "requests": 60, "rps": 6.0, "p95_ms": 50.0},
            {"source": "orders", "target": "inventory", "error_rate": 1.0, "virtual": False,
             "requests": 60, "rps": 6.0, "p95_ms": 2.0},
        ]  # fmt: skip
        return snap

    assessor = Assessor()
    result = None
    for t in range(HYSTERESIS):
        result = assessor.assess(down(t), list(DEFAULT_RULES), t)
    assert result is not None
    assert result.verdicts["inventory"].state == "failing" and result.verdicts["inventory"].by_callers
    assert (
        reason(result.verdicts["inventory"]) == "erro 100% nas chamadas que chegam nele (regra: erro ≥ 25%)"
    )
    assert [c.node for c in result.analysis.causes] == ["inventory"]

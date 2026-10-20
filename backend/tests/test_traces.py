from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traceflow.traces import RawSpan, build_tree, self_time_ms

T0 = datetime(2026, 10, 20, 12, tzinfo=UTC)


def span(span_id: str, parent: str | None, start_ms: float, duration_ms: float, **kw: object) -> RawSpan:
    defaults: dict[str, object] = {"service": "svc", "name": span_id, "kind": "server", "status": "unset"}
    defaults.update(kw)
    return RawSpan(
        span_id=span_id,
        parent_span_id=parent,
        start_time=T0 + timedelta(milliseconds=start_ms),
        duration_ms=duration_ms,
        **defaults,  # type: ignore[arg-type]
    )


def test_compra_vira_arvore_na_ordem_do_waterfall() -> None:
    # gateway -> orders -> (inventory, payments -> bank), embaralhados como chegam do banco
    spans = [
        span("pay", "ord", 90, 290, service="payments"),
        span("gw", None, 0, 420, service="gateway"),
        span("inv", "ord", 20, 60, service="inventory"),
        span("bank", "pay", 100, 270, service="payments", kind="client"),
        span("ord", "gw", 10, 400, service="orders"),
    ]
    tree = build_tree(spans)
    assert [(t.span.span_id, t.depth) for t in tree.spans] == [
        ("gw", 0), ("ord", 1), ("inv", 2), ("pay", 2), ("bank", 3),
    ]  # fmt: skip
    assert tree.duration_ms == 420
    assert tree.services == ["gateway", "inventory", "orders", "payments"]
    pay = next(t for t in tree.spans if t.span.span_id == "pay")
    assert (pay.offset_ms, pay.self_time_ms, pay.children) == (90, 20, 1)  # 290 - 270 esperando o banco


def test_tempo_proprio_com_filhos_em_paralelo_nao_fica_negativo() -> None:
    pai = span("p", None, 0, 100)
    filhos = [span("a", "p", 10, 50), span("b", "p", 20, 50), span("c", "p", 90, 40)]
    # cobertos: [10, 70] e [90, 100] (o c passa do fim do pai e é recortado) = 70 ms
    assert self_time_ms(pai, filhos) == pytest.approx(30)


def test_span_cujo_pai_nao_chegou_vira_orfao_na_raiz() -> None:
    tree = build_tree([span("gw", None, 0, 100), span("perdido", "nao-existe", 50, 10)])
    perdido = next(t for t in tree.spans if t.span.span_id == "perdido")
    assert perdido.orphan and perdido.depth == 0


def test_ciclo_em_dado_malformado_nao_trava() -> None:
    tree = build_tree([span("a", "b", 0, 10), span("b", "a", 5, 10)])
    assert sorted(t.span.span_id for t in tree.spans) == ["a", "b"]


def test_conta_erros_e_recusa_trace_vazio() -> None:
    tree = build_tree([span("a", None, 0, 10, status="error"), span("b", "a", 1, 5, status="error")])
    assert tree.error_count == 2
    with pytest.raises(ValueError):
        build_tree([])

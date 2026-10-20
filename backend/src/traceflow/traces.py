"""Monta a árvore de um trace a partir dos spans soltos que vêm do banco.

Os spans chegam numa lista plana; o parentesco está no parent_span_id. Daqui saem, na ordem
em que o waterfall desenha (pai, depois os filhos em ordem de início):

    depth          a profundidade na árvore (o recuo no waterfall)
    offset_ms      quando o span começou, contado do início do trace
    self_time_ms   o tempo próprio: a duração menos o tempo em que algum filho estava rodando
    orphan         o pai não está no trace (ainda não chegou, ou se perdeu)

É lógica pura, sem banco nem HTTP: testada sozinha.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class RawSpan:
    span_id: str
    parent_span_id: str | None
    service: str
    name: str
    kind: str
    start_time: datetime
    duration_ms: float
    status: str
    status_message: str | None = None
    http_method: str | None = None
    http_route: str | None = None
    http_status_code: int | None = None
    peer_address: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    resource: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(milliseconds=self.duration_ms)


@dataclass(frozen=True)
class TreeSpan:
    span: RawSpan
    depth: int
    offset_ms: float
    self_time_ms: float
    orphan: bool
    children: int


@dataclass(frozen=True)
class TraceTree:
    start_time: datetime
    duration_ms: float
    spans: list[TreeSpan]
    services: list[str]
    error_count: int


def build_tree(spans: Sequence[RawSpan]) -> TraceTree:
    if not spans:
        raise ValueError("trace sem spans")
    start = min(s.start_time for s in spans)
    end = max(s.end_time for s in spans)
    by_id = {s.span_id: s for s in spans}
    children: dict[str | None, list[RawSpan]] = defaultdict(list)
    roots: list[RawSpan] = []
    orphans: set[str] = set()
    for s in spans:
        if s.parent_span_id is None:
            roots.append(s)
        elif s.parent_span_id in by_id and s.parent_span_id != s.span_id:
            children[s.parent_span_id].append(s)
        else:
            # o pai não chegou (ou o span aponta para si mesmo): vira raiz, marcado como órfão
            roots.append(s)
            orphans.add(s.span_id)

    ordered: list[TreeSpan] = []
    seen: set[str] = set()

    def visit(s: RawSpan, depth: int) -> None:
        if s.span_id in seen:  # proteção contra ciclos em dados malformados
            return
        seen.add(s.span_id)
        kids = sorted(children.get(s.span_id, []), key=lambda k: k.start_time)
        ordered.append(
            TreeSpan(
                span=s,
                depth=depth,
                offset_ms=_ms(s.start_time - start),
                self_time_ms=self_time_ms(s, kids),
                orphan=s.span_id in orphans,
                children=len(kids),
            )
        )
        for kid in kids:
            visit(kid, depth + 1)

    for root in sorted(roots, key=lambda r: r.start_time):
        visit(root, 0)
    # spans presos num ciclo (A filho de B, B filho de A) nunca são alcançados a partir de uma raiz
    for s in sorted(spans, key=lambda x: x.start_time):
        if s.span_id not in seen:
            visit(s, 0)

    return TraceTree(
        start_time=start,
        duration_ms=_ms(end - start),
        spans=ordered,
        services=sorted({s.service for s in spans}),
        error_count=sum(1 for s in spans if s.status == "error"),
    )


def self_time_ms(span: RawSpan, children: Iterable[RawSpan]) -> float:
    """A duração menos o tempo coberto por filhos.

    Filhos podem rodar em paralelo (sobrepostos) e até passar do fim do pai: soma-se a união
    dos intervalos dos filhos, recortada à janela do pai. Somar as durações direto daria
    tempo próprio negativo com chamadas em paralelo.
    """
    window_start, window_end = span.start_time, span.end_time
    intervals = sorted(
        (max(c.start_time, window_start), min(c.end_time, window_end))
        for c in children
        if c.end_time > window_start and c.start_time < window_end
    )
    covered = timedelta()
    current_start: datetime | None = None
    current_end: datetime | None = None
    for begin, finish in intervals:
        if current_end is None or begin > current_end:
            if current_start is not None and current_end is not None:
                covered += current_end - current_start
            current_start, current_end = begin, finish
        else:
            current_end = max(current_end, finish)
    if current_start is not None and current_end is not None:
        covered += current_end - current_start
    return max(0.0, span.duration_ms - _ms(covered))


def _ms(delta: timedelta) -> float:
    return delta.total_seconds() * 1000

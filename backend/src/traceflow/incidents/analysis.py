"""A análise de um momento doente: causa provável, raio de impacto e severidade (capítulo 11).

Tudo aqui é função pura sobre um grafo pequeno (os nós e as ligações do retrato), testada
sem banco nem Redis.

**Causa provável.** Num sistema de serviços, a falha sobe: o payments quebra, o orders, que
depende dele, falha junto, e o gateway também. Os três estão doentes, mas só um é a causa.
1. Pega o subgrafo dos nós doentes.
2. Agrupa os ciclos (A chama B, B chama A) em componentes fortemente conexos (Tarjan): dentro
   de um ciclo não dá para dizer quem começou, então o grupo vale como um nó só.
3. Os candidatos são os SUMIDOUROS: grupos doentes que não dependem de nenhum outro doente.
4. Um doente que não é sumidouro ainda pode ser causa, se a doença das dependências não
   explicar a dele (o orders com 30% de erro chamando um payments com 2%).
É correlação, não prova: por isso "provável", e por isso cada causa vem com o motivo.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from traceflow.incidents.rules import RELATIVE_MIN_DELTA_MS, SEVERITY_OF_STATE, State

Severity = Literal["SEV1", "SEV2", "SEV3"]
FAILING_ERROR_RATE = 0.25  # um endpoint de entrada com 25% de erro: SEV1
DEGRADED_ERROR_RATE = 0.05  # com 5%: SEV2
EXPLAIN_ERROR_MARGIN = 0.05  # o erro de quem chama "cabe" no das dependências, com 5 pontos de folga
EXPLAIN_LATENCY_FACTOR = 1.2  # a piora de quem chama "cabe" em 1,2x a da dependência, mais 50 ms


@dataclass(frozen=True)
class Node:
    name: str
    state: State
    error_rate: float = 0.0
    p95_ms: float | None = None
    baseline_ms: float | None = None
    sick_by: Literal["errors", "latency", "traffic", "unresponsive", None] = None

    @property
    def delta_ms(self) -> float | None:
        if self.p95_ms is None or self.baseline_ms is None:
            return None
        return self.p95_ms - self.baseline_ms


@dataclass(frozen=True)
class Call:
    source: str
    target: str
    error_rate: float = 0.0


@dataclass(frozen=True)
class Endpoint:
    route: str  # "POST /checkout"
    service: str  # por onde entrou
    nodes: frozenset[str]  # por onde as requisições desta rota passaram
    rps: float
    error_rate: float
    p95_ms: float | None
    requests: int
    baseline_ms: float | None = None


@dataclass(frozen=True)
class Cause:
    node: str
    own: bool  # True: doente além do que as dependências explicam (não é sumidouro)


@dataclass
class Analysis:
    causes: list[Cause] = field(default_factory=list)
    affected: list[str] = field(default_factory=list)  # doentes por causa da causa (acima dela no grafo)
    at_risk: list[str] = field(default_factory=list)  # dependem da causa, mas ainda estão bem
    endpoints: list[Endpoint] = field(default_factory=list)  # rotas de entrada que passam pela causa
    severity: Severity = "SEV3"


def strongly_connected(nodes: Iterable[str], edges: Mapping[str, Iterable[str]]) -> list[list[str]]:
    """Tarjan, sem recursão (uma cadeia longa estouraria o limite de recursão do Python).

    Devolve os componentes; cada nó fica em exatamente um. Um nó sem ciclo é um componente só dele.
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0
    for root in sorted(nodes):
        if root in index:
            continue
        work: list[tuple[str, Iterable[str]]] = [(root, iter(sorted(edges.get(root, ()))))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(edges.get(child, ())))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:  # raiz de um componente: desempilha até ela
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))
    return components


def analyze(nodes: Mapping[str, Node], calls: Sequence[Call], endpoints: Sequence[Endpoint]) -> Analysis:
    sick = {name for name, n in nodes.items() if n.state != "healthy"}
    if not sick:
        return Analysis()

    # 1-3. Sumidouros do subgrafo doente, com os ciclos agrupados
    sick_deps: dict[str, set[str]] = defaultdict(set)
    for c in calls:
        if c.source in sick and c.target in sick and c.source != c.target:
            sick_deps[c.source].add(c.target)
    components = strongly_connected(sick, sick_deps)
    group_of = {member: i for i, comp in enumerate(components) for member in comp}
    causes: list[Cause] = []
    for i, comp in enumerate(components):
        leaves_group = any(group_of[d] != i for member in comp for d in sick_deps[member])
        if not leaves_group:
            causes.extend(Cause(member, own=False) for member in comp)
    # 4. Doentes que não são sumidouro, mas cuja doença as dependências não explicam
    edge_failure = {(c.source, c.target): c.error_rate for c in calls}
    for name in sorted(sick):
        if any(c.node == name for c in causes):
            continue
        deps = [nodes[d] for d in sick_deps[name] if d in nodes]
        if not _explained(nodes[name], deps, edge_failure):
            causes.append(Cause(name, own=True))
    causes.sort(key=lambda c: (-SEVERITY_OF_STATE[nodes[c.node].state], c.own, c.node))

    # Raio de impacto: quem está ACIMA das causas (chama, direta ou indiretamente)
    callers: dict[str, set[str]] = defaultdict(set)
    for c in calls:
        if c.source != c.target:
            callers[c.target].add(c.source)
    cause_names = {c.node for c in causes}
    above: set[str] = set()
    frontier = list(cause_names)
    while frontier:
        for caller in callers[frontier.pop()]:
            if caller not in above and caller not in cause_names:
                above.add(caller)
                frontier.append(caller)
    affected = sorted(above & sick)
    at_risk = sorted(above - sick)

    # As rotas de entrada que passam pela causa: é aqui que quem usa sente
    hit = sorted((e for e in endpoints if e.nodes & cause_names), key=lambda e: (-e.error_rate, e.route))
    return Analysis(causes, affected, at_risk, hit, _severity(hit, endpoints, nodes, cause_names))


def _explained(node: Node, deps: Sequence[Node], edge_failure: Mapping[tuple[str, str], float]) -> bool:
    """A doença deste nó cabe na das dependências doentes? (Se não houver dados, assume que sim.)"""
    if not deps:
        return False
    if node.sick_by == "errors":
        worst = max(edge_failure.get((node.name, d.name), 0.0) for d in deps)
        return node.error_rate <= worst + EXPLAIN_ERROR_MARGIN
    if node.sick_by == "latency":
        mine = node.delta_ms
        theirs = [d.delta_ms for d in deps if d.delta_ms is not None]
        if mine is None or not theirs:
            return True
        return mine <= max(theirs) * EXPLAIN_LATENCY_FACTOR + RELATIVE_MIN_DELTA_MS
    return True


def _severity(
    endpoints: Sequence[Endpoint], known: Sequence[Endpoint], nodes: Mapping[str, Node], causes: set[str]
) -> Severity:
    """A severidade sai do efeito em quem USA (as rotas de entrada), não do serviço que quebrou."""
    if any(nodes[c].state == "unresponsive" and _is_entry(c, known) for c in causes):
        return "SEV1"  # a porta de entrada caiu
    if any(e.error_rate >= FAILING_ERROR_RATE for e in endpoints):
        return "SEV1"
    for e in endpoints:
        slow = (
            e.p95_ms is not None
            and e.baseline_ms is not None
            and e.p95_ms >= 2 * e.baseline_ms
            and e.p95_ms - e.baseline_ms >= RELATIVE_MIN_DELTA_MS
        )
        if e.error_rate >= DEGRADED_ERROR_RATE or slow:
            return "SEV2"
    return "SEV3"  # dependência doente, mas quem usa não sente (o notifications caído, por exemplo)


def _is_entry(node: str, endpoints: Sequence[Endpoint]) -> bool:
    return any(e.service == node for e in endpoints)

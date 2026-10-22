import dagre from "@dagrejs/dagre";

import { ERROR_ALERT } from "@/lib/live";

/**
 * O mapa de serviços como dados: quem existe (nós) e quem chama quem (ligações).
 *
 * O retrato ao vivo e o histórico (GET /map) têm o mesmo formato, então os dois passam por
 * aqui e são desenhados pelo mesmo componente. Nada de React aqui: são funções puras,
 * testadas sozinhas (service-map.test.ts).
 */

export const CLIENTS = "__clientes__"; // quem está fora do sistema: as requisições que entram

export type CallStats = { rps: number; error_rate: number | null; p50_ms: number | null; p95_ms: number | null; requests: number };

export type MapNode = {
  id: string; // o nome do serviço, o endereço (nó virtual) ou CLIENTS
  kind: "service" | "virtual" | "clients";
  label: string;
  detail: string | null; // o endereço completo dos nós virtuais
  stats: CallStats | null; // o que o serviço atendeu; no virtual, o que chegou nele; null = nada no período
  unresponsive: boolean;
};

export type MapEdge = {
  id: string;
  source: string;
  target: string;
  stats: CallStats;
  failing: boolean; // falha (5xx ou sem resposta) acima da régua de 5%
};

export type ServiceGraph = { nodes: MapNode[]; edges: MapEdge[] };

type ServiceInput = {
  name: string;
  rps: number;
  error_rate: number;
  p50_ms: number | null;
  p95_ms: number | null;
  requests: number;
  entry_rps: number;
};
type EdgeInput = {
  source: string;
  target: string;
  address: string;
  virtual: boolean;
  rps: number;
  error_rate: number;
  p50_ms: number | null;
  p95_ms: number | null;
  requests: number;
};

export function buildGraph({
  services,
  edges,
  unresponsive = [],
}: {
  services: ServiceInput[];
  edges: EdgeInput[];
  unresponsive?: string[];
}): ServiceGraph {
  const nodes = new Map<string, MapNode>();
  const down = new Set(unresponsive);
  const service = (name: string): MapNode => ({
    id: name,
    kind: "service",
    label: name,
    detail: null,
    stats: null,
    unresponsive: down.has(name),
  });

  for (const s of services) {
    nodes.set(s.name, {
      ...service(s.name),
      stats: { rps: s.rps, error_rate: s.error_rate, p50_ms: s.p50_ms, p95_ms: s.p95_ms, requests: s.requests },
    });
  }

  const result: MapEdge[] = [];
  for (const e of edges) {
    if (e.source === e.target) continue; // um serviço chamando a si mesmo não acrescenta nada ao mapa
    // quem só aparece nas ligações também é um nó: o serviço que caiu (não atende mais nada)
    // e quem chama sem atender (um job, por exemplo)
    if (!nodes.has(e.source)) nodes.set(e.source, service(e.source));
    if (!nodes.has(e.target)) {
      nodes.set(
        e.target,
        e.virtual
          ? { id: e.target, kind: "virtual", label: hostOf(e.address), detail: e.address, stats: null, unresponsive: false }
          : service(e.target),
      );
    }
    const target = nodes.get(e.target)!;
    if (target.kind === "virtual") target.stats = addCalls(target.stats, e); // ninguém o mede por dentro: soma o que chegou
    result.push({
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      stats: { rps: e.rps, error_rate: e.error_rate, p50_ms: e.p50_ms, p95_ms: e.p95_ms, requests: e.requests },
      failing: e.error_rate >= ERROR_ALERT,
    });
  }

  const doors = services.filter((s) => s.entry_rps > 0);
  if (doors.length) {
    nodes.set(CLIENTS, { id: CLIENTS, kind: "clients", label: "Clientes", detail: null, stats: null, unresponsive: false });
    for (const s of doors) {
      result.push({
        id: `${CLIENTS}->${s.name}`,
        source: CLIENTS,
        target: s.name,
        // a falha de quem entra é a do próprio serviço de entrada, que já está no nó dele
        stats: { rps: s.entry_rps, error_rate: null, p50_ms: null, p95_ms: null, requests: 0 },
        failing: false,
      });
    }
  }

  return { nodes: [...nodes.values()], edges: result };
}

function hostOf(address: string): string {
  return address.replace(/:\d+$/, "");
}

function addCalls(current: CallStats | null, e: EdgeInput): CallStats {
  if (!current) return { rps: e.rps, error_rate: e.error_rate, p50_ms: null, p95_ms: e.p95_ms, requests: e.requests };
  const requests = current.requests + e.requests;
  const failures = (current.error_rate ?? 0) * current.requests + e.error_rate * e.requests;
  return {
    rps: current.rps + e.rps,
    error_rate: requests ? failures / requests : 0,
    p50_ms: null,
    p95_ms: Math.max(current.p95_ms ?? 0, e.p95_ms ?? 0) || null, // sem os histogramas, o maior p95 é o honesto
    requests,
  };
}

// tamanhos pensados para a loja inteira caber na largura sem o zoom encolher o texto
export const NODE_SIZE = { service: { width: 168, height: 76 }, virtual: { width: 168, height: 76 }, clients: { width: 112, height: 40 } };

/**
 * As posições, da esquerda para a direita, no sentido das chamadas: quem entra, quem é
 * chamado por ele, e assim por diante. O dagre organiza em camadas e reduz os cruzamentos.
 * A posição sai só da estrutura (quem existe e quem chama quem), não dos números: o mapa
 * não se mexe a cada segundo, só quando aparece ou some um serviço ou uma ligação.
 */
export function layoutGraph(
  graph: ServiceGraph,
  direction: "LR" | "TB" = "LR", // TB: de cima para baixo, para telas estreitas (celular)
): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: direction, nodesep: direction === "LR" ? 28 : 20, ranksep: direction === "LR" ? 72 : 56, marginx: 16, marginy: 16 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of [...graph.nodes].sort((a, b) => a.id.localeCompare(b.id))) {
    g.setNode(n.id, { ...NODE_SIZE[n.kind] });
  }
  for (const e of graph.edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  const positions = new Map<string, { x: number; y: number }>();
  for (const n of graph.nodes) {
    const { x, y } = g.node(n.id);
    const { width, height } = NODE_SIZE[n.kind];
    positions.set(n.id, { x: x - width / 2, y: y - height / 2 }); // o dagre dá o centro; o React Flow quer o canto
  }
  return positions;
}

/** A "forma" do grafo: muda só quando nós ou ligações aparecem ou somem (aí sim, refaz o layout). */
export function graphShape(graph: ServiceGraph): string {
  return [...graph.nodes.map((n) => n.id).sort(), "|", ...graph.edges.map((e) => e.id).sort()].join(",");
}

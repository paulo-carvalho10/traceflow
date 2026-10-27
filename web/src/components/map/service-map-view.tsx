"use client";

import "@xyflow/react/dist/style.css";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Background,
  BaseEdge,
  Controls,
  type Edge,
  type EdgeProps,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  type Node,
  type NodeHandle,
  type NodeProps,
  Position,
  ReactFlow,
  getBezierPath,
  useNodesInitialized,
  useReactFlow,
  useStore,
} from "@xyflow/react";
import { Crosshair, Globe, TriangleAlert, Users } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import { IncidentBanner } from "@/components/incidents/badges";
import { LiveEmpty } from "@/components/live-controls";
import { Panel } from "@/components/panel";
import { RANGES, useWorkspace } from "@/components/workspace";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useMediaQuery } from "@/hooks/use-media-query";
import { api } from "@/lib/api";
import { formatDuration, formatPercent, formatRate } from "@/lib/format";
import { STATE, TONE_TEXT } from "@/lib/incidents";
import { ERROR_ALERT, type HealthState, type LiveSnapshot } from "@/lib/live";
import {
  CLIENTS,
  type CallStats,
  type MapEdge,
  type MapNode,
  NODE_SIZE,
  type ServiceGraph,
  buildGraph,
  graphShape,
  layoutGraph,
} from "@/lib/service-map";
import { cn } from "@/lib/utils";


type NodeHealth = { state: HealthState; reason: string; cause: boolean } | null;
type ServiceNodeType = Node<{ node: MapNode; health: NodeHealth; vertical: boolean }, "service">;
type ClientsNodeType = Node<{ node: MapNode; health: NodeHealth; vertical: boolean }, "clients">;
type CallEdgeType = Edge<{ edge: MapEdge }, "call">;

/**
 * O mapa de serviços: quem chama quem, com a taxa e a falha de cada ligação. Ao vivo (o
 * retrato de cada segundo, pelo WebSocket) ou de um período passado (GET /map): os dois têm
 * o mesmo formato e passam pelo mesmo buildGraph.
 */
export function ServiceMapView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { projectId, environment, environments, environmentsLoading, live: liveData, window, range, scoped } = useWorkspace();
  // o mapa calcula sobre os spans brutos: 24 h ou 3 dias seriam milhões de linhas (capítulo 27)
  const tooLong = RANGES[range].minutes > 360;
  const live = params.get("view") !== "period" || tooLong;
  const { snapshot, status } = liveData;
  const history = useQuery({
    queryKey: ["map", projectId, environment, window],
    queryFn: () => api.serviceMap(projectId, { environment: environment!, ...window! }),
    enabled: !live && environment !== undefined && window !== null,
    placeholderData: keepPreviousData,
  });

  const graph = useMemo<ServiceGraph | null>(() => {
    const source = live ? snapshot : history.data;
    return source ? buildGraph(source) : null;
  }, [live, snapshot, history.data]);

  function setView(value: "live" | "period") {
    const next = new URLSearchParams(params);
    if (value === "live") next.delete("view");
    else next.set("view", value);
    router.replace(`${pathname}?${next}`, { scroll: false });
  }

  const loading = environmentsLoading;
  if (!loading && environments.length === 0) {
    return (
      <p className="px-4 py-16 text-center text-[13px] text-muted-foreground sm:px-6">
        Nenhum span chegou a este projeto ainda. Crie uma chave de ingestão e configure a sua aplicação.
      </p>
    );
  }

  const stale = live && status === "sem dados novos";
  // a saúde e a causa só existem ao vivo: o histórico mostra o que aconteceu, não um diagnóstico
  const health = healthOf(live ? snapshot : null);
  const waiting = live ? status === "conectando" || status === "reconectando" : history.isPending;
  const empty = graph !== null && graph.nodes.length === 0;

  return (
    <div className="space-y-3 px-4 pb-8 sm:px-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex h-7 overflow-hidden rounded-md border text-xs" role="group" aria-label="O que o mapa mostra">
          {(["live", "period"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              disabled={v === "period" && tooLong}
              aria-pressed={(v === "live") === live}
              className={cn(
                "px-2.5 transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-40",
                (v === "live") === live ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {v === "live" ? "Ao vivo" : RANGES[range].label}
            </button>
          ))}
        </div>
        <span className="text-xs text-faint">
          {live
            ? "o último minuto, atualizado a cada segundo"
            : "todas as chamadas do período, com percentis exatos"}
          {tooLong && " · o mapa por período vai até 6 h"}
        </span>
      </div>

      {live && snapshot?.incident && <IncidentBanner incident={snapshot.incident} projectId={projectId} />}

      <figure className="space-y-2">
        {graph && !empty ? (
          <div
            className={cn("h-[560px] rounded-lg border bg-card transition-opacity xl:h-[600px]", stale && "opacity-50")}
            aria-label="Mapa de serviços"
          >
            <ServiceFlow
              graph={graph}
              health={health}
              onOpen={(service) => router.push(scoped(`/projects/${projectId}/services/${encodeURIComponent(service)}`))}
            />
          </div>
        ) : waiting && !graph ? (
          <Skeleton className="h-[560px] rounded-lg" />
        ) : live ? (
          <LiveEmpty status={status}>
            Nenhuma chamada entre serviços no último minuto. Assim que o tráfego chegar, o mapa se desenha sozinho.
          </LiveEmpty>
        ) : (
          <p className="rounded-lg border border-dashed px-4 py-6 text-[13px] text-muted-foreground">
            Nenhuma chamada entre serviços neste período.
          </p>
        )}
        <figcaption className="max-w-5xl text-xs text-faint">
          A seta vai de quem chama para quem é chamado, e os números são medidos do lado de quem chama: é ele que
          sente a falha. Falha é resposta 5xx ou falta de resposta; um 4xx (cartão recusado, produto inexistente) é
          resposta legítima e não conta. Contorno tracejado: sistema externo, que não manda spans. Borda âmbar:
          degradado; vermelha: falhando ou sem resposta; a mira marca a causa provável de um incidente aberto.
          {live ? " Janela: os 10 s que terminam 3 s atrás." : " Percentis exatos, calculados sobre os spans do período."}
        </figcaption>
      </figure>

      {graph && graph.edges.length > 0 && <CallsTable graph={graph} live={live} />}
    </div>
  );
}

const nodeTypes = { service: ServiceNode, clients: ClientsNode };
const edgeTypes = { call: CallEdge };

/** A saúde de cada nó, tirada do retrato ao vivo (null: sem retrato, como no histórico). */
function healthOf(snapshot: LiveSnapshot | null | undefined): (id: string) => NodeHealth {
  return (id) => {
    const h = snapshot?.health?.[id];
    // em recuperação a causa já está saudável: a marca sai, e a faixa diz que está recuperando
    const incident = snapshot?.incident;
    const cause = incident && !incident.healthy_since ? incident.causes.some((c) => c.node === id) : false;
    return h ? { state: h.state, reason: h.reason, cause } : cause ? { state: "degraded", reason: "", cause } : null;
  };
}

/** Só o desenho ao vivo, sem os controles nem a tabela: o Playground o mostra ao lado dos botões. */
export function LiveServiceMap({
  snapshot,
  onOpen,
  direction,
}: {
  snapshot: LiveSnapshot;
  onOpen: (service: string) => void;
  direction?: "LR" | "TB"; // força a direção (numa coluna estreita, o desenho vertical cabe melhor)
}) {
  const graph = useMemo(() => buildGraph(snapshot), [snapshot]);
  if (graph.nodes.length === 0) {
    return <p className="p-6 text-sm text-muted-foreground">Nenhuma chamada entre serviços no último minuto.</p>;
  }
  return <ServiceFlow graph={graph} health={healthOf(snapshot)} onOpen={onOpen} direction={direction} />;
}

function ServiceFlow({
  graph,
  health,
  onOpen,
  direction,
}: {
  graph: ServiceGraph;
  health: (id: string) => NodeHealth;
  onOpen: (service: string) => void;
  direction?: "LR" | "TB";
}) {
  // no celular, o mapa desce em vez de ir para o lado: cabe na largura sem encolher o texto
  const narrow = useMediaQuery("(max-width: 640px)");
  const vertical = direction ? direction === "TB" : narrow;
  const positions = useMemo(() => layoutGraph(graph, vertical ? "TB" : "LR"), [graph, vertical]);
  // A medida e as alças vão prontas em cada nó. O mapa recria os nós a cada segundo (os números
  // mudam), e um nó novo SEM medida faz o React Flow esquecer as medidas e as alças e esconder
  // o nó até medir de novo pelo navegador. Quase sempre dava tempo; às vezes não, e o mapa
  // sumia para sempre no meio de um incidente. Os nós têm tamanho fixo: não há o que medir.
  const nodes: (ServiceNodeType | ClientsNodeType)[] = graph.nodes.map((n) => ({
    id: n.id,
    type: n.kind === "clients" ? "clients" : "service",
    position: positions.get(n.id)!,
    data: { node: n, health: health(n.id), vertical },
    draggable: false,
    connectable: false,
    style: NODE_SIZE[n.kind],
    measured: NODE_SIZE[n.kind],
    handles: handlesFor(n.kind, NODE_SIZE[n.kind], vertical),
  }));
  const edges: CallEdgeType[] = graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    type: "call",
    data: { edge: e },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 14,
      height: 14,
      color: e.failing ? "var(--warning)" : "var(--muted-foreground)",
    },
  }));
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      colorMode="dark"
      fitView
      fitViewOptions={{ padding: 0.12, maxZoom: 1.1 }} // um mapa pequeno não vira um mapa gigante
      minZoom={0.3}
      maxZoom={1.6}
      nodesConnectable={false}
      onNodeClick={(_, node) => node.data.node.kind === "service" && onOpen(node.id)}
      style={{ background: "transparent" }}
    >
      <Background gap={24} size={1} color="var(--border)" />
      <Controls showInteractive={false} />
      <Refit shape={`${graphShape(graph)}${vertical ? "|v" : ""}`} />
    </ReactFlow>
  );
}

/** Onde as setas entram e saem: no meio dos lados (ou do topo e da base, no desenho vertical). */
function handlesFor(kind: MapNode["kind"], size: { width: number; height: number }, vertical: boolean): NodeHandle[] {
  const { width, height } = size;
  const source: NodeHandle = vertical
    ? { type: "source", position: Position.Bottom, x: width / 2, y: height, width: 1, height: 1 }
    : { type: "source", position: Position.Right, x: width, y: height / 2, width: 1, height: 1 };
  const target: NodeHandle = vertical
    ? { type: "target", position: Position.Top, x: width / 2, y: 0, width: 1, height: 1 }
    : { type: "target", position: Position.Left, x: 0, y: height / 2, width: 1, height: 1 };
  return kind === "clients" ? [source] : [source, target]; // ninguém chama os clientes
}

/**
 * Enquadra o desenho de novo quando a FORMA muda (um nó ou uma ligação aparece ou some, ou a
 * direção troca) ou quando a área do mapa muda de tamanho. O mapa continua montado: só os
 * números mudam a cada segundo, sem nada se mexer. (A primeira versão remontava o mapa inteiro
 * pela key, e uma remontagem no meio de uma mudança de tamanho podia enquadrar fora da área.)
 */
function Refit({ shape }: { shape: string }) {
  const { fitView } = useReactFlow();
  const measured = useNodesInitialized();
  const width = useStore((s) => s.width);
  const height = useStore((s) => s.height);
  useEffect(() => {
    if (!measured || width <= 0 || height <= 0) return;
    // Espera dois quadros: as posições novas (uma troca de direção, um nó novo) chegam ao
    // React Flow num efeito dele, que roda DEPOIS deste. Enquadrar aqui, na hora, usaria as
    // posições antigas, e o desenho ficava fora da área visível.
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => void fitView({ padding: 0.12, maxZoom: 1.1 }));
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [shape, measured, width, height, fitView]);
  return null;
}

function ServiceNode({ data }: NodeProps<ServiceNodeType>) {
  const { node, health } = data;
  const virtual = node.kind === "virtual";
  const state: HealthState = node.unresponsive ? "unresponsive" : (health?.state ?? "healthy");
  const tone = STATE[state].tone;
  return (
    <div
      className={cn(
        "relative flex size-full flex-col justify-center gap-0.5 rounded-md border bg-background px-3 text-left",
        virtual && "border-dashed",
        tone === "warning" && "border-warning",
        tone === "critical" && "border-destructive",
        health?.cause && "ring-2 ring-destructive/40 ring-offset-2 ring-offset-card",
        !virtual && "cursor-pointer hover:border-primary",
      )}
      title={[
        virtual ? `${node.detail}: sistema externo, medido pelas chamadas que chegam nele` : `Abrir ${node.label}`,
        health && state !== "healthy" ? `${STATE[state].label}: ${health.reason}` : "",
      ]
        .filter(Boolean)
        .join("\n")}
    >
      {health?.cause && (
        <span className="absolute -top-2.5 left-2 flex items-center gap-1 rounded-full border border-destructive/50 bg-card px-1.5 text-[10px] font-medium text-destructive">
          <Crosshair className="size-3" /> causa provável
        </span>
      )}
      <Handle type="target" position={data.vertical ? Position.Top : Position.Left} isConnectable={false} className="!border-0 !bg-transparent" />
      <div className="flex items-center gap-2 font-mono text-[13px]">
        {virtual ? (
          <Globe className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <span
            className={cn(
              "size-1.5 shrink-0 rounded-full",
              tone === "critical" ? "bg-destructive" : tone === "warning" ? "bg-warning" : "bg-success",
            )}
            aria-hidden
          />
        )}
        <span className="truncate">{node.label}</span>
        {state !== "healthy" ? (
          <span className={cn("ml-auto shrink-0 text-[10px] font-medium", TONE_TEXT[tone])}>{STATE[state].label}</span>
        ) : (
          virtual && <span className="ml-auto shrink-0 text-[10px] font-normal text-muted-foreground">externo</span>
        )}
      </div>
      {state === "unresponsive" ? (
        <span className="flex items-center gap-1 text-xs font-medium text-destructive">
          <TriangleAlert className="size-3.5" /> sem resposta
        </span>
      ) : (
        <NodeStats stats={node.stats} />
      )}
      <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} isConnectable={false} className="!border-0 !bg-transparent" />
    </div>
  );
}

function ClientsNode({ data }: NodeProps<ClientsNodeType>) {
  return (
    <div className="flex size-full items-center justify-center gap-2 rounded-full border bg-background text-sm text-muted-foreground">
      <Users className="size-4" /> {data.node.label}
      <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} isConnectable={false} className="!border-0 !bg-transparent" />
    </div>
  );
}

/** Duas linhas fixas, sem quebra: a taxa e a falha; o p95. */
function NodeStats({ stats }: { stats: CallStats | null }) {
  if (!stats || stats.requests === 0) return <span className="text-xs text-muted-foreground">sem tráfego</span>;
  const failing = (stats.error_rate ?? 0) >= ERROR_ALERT;
  return (
    <div className="font-mono text-[11px] whitespace-nowrap text-muted-foreground tabular">
      <div className="flex items-center gap-1">
        {formatRate(stats.rps)} ·
        <span className={cn("flex items-center gap-0.5", failing && "text-warning")}>
          {failing && <TriangleAlert className="size-3" />}
          {formatPercent(stats.error_rate)} falha
        </span>
      </div>
      <div>p95 {stats.p95_ms === null ? "–" : formatDuration(stats.p95_ms)}</div>
    </div>
  );
}

function CallEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }: EdgeProps<CallEdgeType>) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const edge = data!.edge;
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{ stroke: edge.failing ? "var(--warning)" : "var(--muted-foreground)", strokeWidth: edge.failing ? 2 : 1.25 }}
      />
      <EdgeLabelRenderer>
        {/* rótulo curto, para caber nas ligações curtas: a taxa, ou a falha quando ela passa
            de 5%; o resto está na dica do mouse e na tabela abaixo do mapa */}
        <div
          className={cn(
            "nodrag nopan absolute flex items-center gap-0.5 rounded-md border bg-card px-1.5 py-0.5 font-mono text-[10px] tabular",
            edge.failing ? "border-warning/50 text-warning" : "text-muted-foreground",
          )}
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, pointerEvents: "all" }}
          title={edgeSummary(edge)}
        >
          {edge.failing ? (
            <>
              <TriangleAlert className="size-3" /> {formatPercent(edge.stats.error_rate)}
            </>
          ) : (
            formatRate(edge.stats.rps)
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

function edgeSummary(edge: MapEdge): string {
  const { rps, error_rate, p95_ms } = edge.stats;
  const parts = [formatRate(rps)];
  if (error_rate !== null) parts.push(`falha ${formatPercent(error_rate)}`);
  if (p95_ms !== null) parts.push(`p95 ${formatDuration(p95_ms)}`);
  return parts.join(" · ");
}

/** Os mesmos números do mapa em tabela: o desenho nunca é o único caminho até o número. */
function CallsTable({ graph, live }: { graph: ServiceGraph; live: boolean }) {
  const label = (id: string) => (id === CLIENTS ? "Clientes (entrada)" : graph.nodes.find((n) => n.id === id)?.label ?? id);
  const rows = [...graph.edges].sort((a, b) =>
    a.source === CLIENTS ? -1 : b.source === CLIENTS ? 1 : a.source.localeCompare(b.source) || a.target.localeCompare(b.target),
  );
  const ms = (v: number | null) => (v === null ? "–" : formatDuration(v));
  return (
    <Panel title="Chamadas entre serviços" description="Medidas do lado de quem chama">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>De</TableHead>
            <TableHead>Para</TableHead>
            <TableHead className="text-right">Chamadas/s</TableHead>
            {!live && <TableHead className="text-right">Chamadas</TableHead>}
            <TableHead className="text-right">Falha</TableHead>
            <TableHead className="text-right">p50</TableHead>
            <TableHead className="text-right">p95</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((e) => (
            <TableRow key={e.id}>
              <TableCell className={cn("text-xs", e.source !== CLIENTS && "font-mono")}>{label(e.source)}</TableCell>
              <TableCell className="font-mono text-xs">{label(e.target)}</TableCell>
              <TableCell className="text-right font-mono text-xs tabular">{formatRate(e.stats.rps)}</TableCell>
              {!live && (
                <TableCell className="text-right font-mono text-xs tabular">
                  {e.source === CLIENTS ? "–" : e.stats.requests.toLocaleString("pt-BR")}
                </TableCell>
              )}
              <TableCell className={cn("text-right font-mono text-xs tabular", e.failing && "text-warning")}>
                {formatPercent(e.stats.error_rate)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular">{ms(e.stats.p50_ms)}</TableCell>
              <TableCell className="text-right font-mono text-xs tabular">{ms(e.stats.p95_ms)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Panel>
  );
}

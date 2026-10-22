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
  type NodeProps,
  Position,
  ReactFlow,
  getBezierPath,
} from "@xyflow/react";
import { Globe, TriangleAlert, Users } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { EnvironmentSelect, LiveBadge, LiveEmpty, useEnvironment } from "@/components/live-controls";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useLive } from "@/hooks/use-live";
import { api } from "@/lib/api";
import { serviceColor } from "@/lib/colors";
import { formatDuration, formatPercent, formatRate } from "@/lib/format";
import { ERROR_ALERT } from "@/lib/live";
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

// 24 h e 3 dias ficam de fora: a rota calcula sobre os spans brutos, e um dia inteiro de
// tráfego são milhões de linhas. O próximo passo para eles é agregar por minuto (capítulo 27).
const PERIODS = { "15m": 15, "1h": 60, "6h": 360 } as const;
type Period = "live" | keyof typeof PERIODS;

type ServiceNodeType = Node<{ node: MapNode }, "service">;
type ClientsNodeType = Node<{ node: MapNode }, "clients">;
type CallEdgeType = Edge<{ edge: MapEdge }, "call">;

/**
 * O mapa de serviços: quem chama quem, com a taxa e a falha de cada ligação. Ao vivo (o
 * retrato de cada segundo, pelo WebSocket) ou de um período passado (GET /map): os dois têm
 * o mesmo formato e passam pelo mesmo buildGraph.
 */
export function ServiceMapView({ projectId }: { projectId: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const period = (params.get("period") as Period | null) ?? "live";
  const live = period === "live";
  const { environment, environments, loading, choose } = useEnvironment(projectId);
  // no histórico, o WebSocket nem abre: environment undefined desliga o useLive
  const { snapshot, status } = useLive(projectId, live ? environment : undefined);

  const timeWindow = useQuery({
    queryKey: ["window", period],
    queryFn: () => {
      const until = new Date();
      const minutes = PERIODS[period as keyof typeof PERIODS];
      return { until: until.toISOString(), since: new Date(until.getTime() - minutes * 60_000).toISOString() };
    },
    enabled: !live,
    refetchInterval: 30_000,
    staleTime: 0,
  });
  const history = useQuery({
    queryKey: ["map", projectId, environment, timeWindow.data],
    queryFn: () => api.serviceMap(projectId, { environment: environment!, ...timeWindow.data! }),
    enabled: !live && environment !== undefined && timeWindow.isSuccess,
    placeholderData: keepPreviousData,
  });

  const graph = useMemo<ServiceGraph | null>(() => {
    const source = live ? snapshot : history.data;
    return source ? buildGraph(source) : null;
  }, [live, snapshot, history.data]);

  function setPeriod(value: string) {
    const next = new URLSearchParams(params);
    if (value === "live") next.delete("period");
    else next.set("period", value);
    router.replace(`${pathname}?${next}`, { scroll: false });
  }

  if (!loading && environments.length === 0) {
    return (
      <p className="px-8 py-16 text-center text-sm text-muted-foreground">
        Nenhum span chegou a este projeto ainda. Crie uma chave de ingestão e configure a sua aplicação.
      </p>
    );
  }

  const stale = live && status === "sem dados novos";
  const waiting = live ? status === "conectando" || status === "reconectando" : history.isPending;
  const empty = graph !== null && graph.nodes.length === 0;

  return (
    <div className="space-y-6 px-8 py-6">
      <div className="flex flex-wrap items-center gap-3">
        <EnvironmentSelect value={environment} options={environments} onChange={choose} />
        <Select value={period} onValueChange={setPeriod}>
          <SelectTrigger className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="live">Agora (ao vivo)</SelectItem>
            <SelectItem value="15m">Últimos 15 minutos</SelectItem>
            <SelectItem value="1h">Última hora</SelectItem>
            <SelectItem value="6h">Últimas 6 horas</SelectItem>
          </SelectContent>
        </Select>
        {live && <LiveBadge status={status} />}
      </div>

      <figure className="space-y-2">
        {graph && !empty ? (
          <div
            className={cn("h-[480px] rounded-xl border bg-card transition-opacity", stale && "opacity-50")}
            aria-label="Mapa de serviços"
          >
            <ServiceFlow graph={graph} onOpen={(service) => router.push(serviceHref(projectId, service, environment))} />
          </div>
        ) : waiting && !graph ? (
          <Skeleton className="h-[480px] rounded-xl" />
        ) : live ? (
          <LiveEmpty status={status}>
            Nenhuma chamada entre serviços no último minuto. Assim que o tráfego chegar, o mapa se desenha sozinho.
          </LiveEmpty>
        ) : (
          <p className="rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">
            Nenhuma chamada entre serviços neste período.
          </p>
        )}
        <figcaption className="text-xs text-muted-foreground">
          A seta vai de quem chama para quem é chamado, e os números são medidos do lado de quem chama: é ele que
          sente a falha. Falha é resposta 5xx ou falta de resposta; um 4xx (cartão recusado, produto inexistente) é
          resposta legítima e não conta. Contorno tracejado: sistema externo, que não manda spans.
          {live ? " Janela: os 10 s que terminam 3 s atrás." : " Percentis exatos, calculados sobre os spans do período."}
        </figcaption>
      </figure>

      {graph && graph.edges.length > 0 && <CallsTable graph={graph} live={live} />}
    </div>
  );
}

function serviceHref(projectId: number, service: string, environment: string | undefined) {
  return `/projects/${projectId}/services/${encodeURIComponent(service)}${
    environment ? `?environment=${encodeURIComponent(environment)}` : ""
  }`;
}

const nodeTypes = { service: ServiceNode, clients: ClientsNode };
const edgeTypes = { call: CallEdge };

function ServiceFlow({ graph, onOpen }: { graph: ServiceGraph; onOpen: (service: string) => void }) {
  const positions = useMemo(() => layoutGraph(graph), [graph]);
  const nodes: (ServiceNodeType | ClientsNodeType)[] = graph.nodes.map((n) => ({
    id: n.id,
    type: n.kind === "clients" ? "clients" : "service",
    position: positions.get(n.id)!,
    data: { node: n },
    draggable: false,
    connectable: false,
    style: NODE_SIZE[n.kind],
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
      // a chave muda quando aparece ou some um nó ou uma ligação: o mapa remonta e se
      // enquadra de novo; quando só os números mudam, nada se mexe
      key={graphShape(graph)}
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
    </ReactFlow>
  );
}

function ServiceNode({ data }: NodeProps<ServiceNodeType>) {
  const { node } = data;
  const virtual = node.kind === "virtual";
  return (
    <div
      className={cn(
        "flex size-full flex-col justify-center gap-0.5 rounded-xl border bg-background px-3 text-left",
        virtual && "border-dashed",
        node.unresponsive && "border-destructive",
        !virtual && "cursor-pointer hover:border-primary",
      )}
      title={virtual ? `${node.detail}: sistema externo, medido pelas chamadas que chegam nele` : `Abrir ${node.label}`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} className="!border-0 !bg-transparent" />
      <div className="flex items-center gap-2 text-sm font-medium">
        {virtual ? (
          <Globe className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <span className="size-2 shrink-0 rounded-full" style={{ background: serviceColor(node.label) }} />
        )}
        <span className="truncate">{node.label}</span>
        {virtual && <span className="ml-auto shrink-0 text-[10px] font-normal text-muted-foreground">externo</span>}
      </div>
      {node.unresponsive ? (
        <span className="flex items-center gap-1 text-xs font-medium text-destructive">
          <TriangleAlert className="size-3.5" /> sem resposta
        </span>
      ) : (
        <NodeStats stats={node.stats} />
      )}
      <Handle type="source" position={Position.Right} isConnectable={false} className="!border-0 !bg-transparent" />
    </div>
  );
}

function ClientsNode({ data }: NodeProps<ClientsNodeType>) {
  return (
    <div className="flex size-full items-center justify-center gap-2 rounded-full border bg-background text-sm text-muted-foreground">
      <Users className="size-4" /> {data.node.label}
      <Handle type="source" position={Position.Right} isConnectable={false} className="!border-0 !bg-transparent" />
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
    <section className="rounded-xl border bg-card">
      <h2 className="px-4 pt-4 pb-2 text-sm font-medium">Chamadas entre serviços</h2>
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
              <TableCell>{label(e.source)}</TableCell>
              <TableCell>{label(e.target)}</TableCell>
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
    </section>
  );
}

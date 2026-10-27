"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { Sparkline } from "@/components/charts/sparkline";
import { TimeSeries } from "@/components/charts/time-series";
import { HealthLabel, serviceState } from "@/components/health";
import { IncidentBanner } from "@/components/incidents/badges";
import { LiveEmpty } from "@/components/live-controls";
import { Metric, MetricStrip, Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RANGES, useWorkspace } from "@/components/workspace";
import { api } from "@/lib/api";
import { PERCENTILE_COLORS } from "@/lib/colors";
import { formatClock, formatDuration, formatPercent, formatRate } from "@/lib/format";
import { ERROR_ALERT, type LiveEdge, type LiveIncident } from "@/lib/live";
import { cn } from "@/lib/utils";

const ms = (v: number | null | undefined) => (v === null || v === undefined ? "–" : formatDuration(v));

/**
 * Um serviço: os números de agora, o histórico no período do cabeçalho, as rotas que ele
 * atende, de quem depende e quem depende dele, e os traces recentes que passaram por ele.
 */
export function ServiceView({ service }: { service: string }) {
  const { projectId, environment, live: liveData, window, range, scoped } = useWorkspace();
  const { snapshot, status } = liveData;
  const live = snapshot?.services.find((s) => s.name === service);
  const state = serviceState(service, snapshot);
  const params = { environment, ...(window ?? { since: "", until: "" }) };
  const enabled = window !== null && environment !== undefined;
  const metrics = useQuery({
    queryKey: ["metrics", projectId, service, environment, window],
    queryFn: () => api.serviceMetrics(projectId, service, params),
    enabled,
    placeholderData: keepPreviousData, // trocar o período mantém o desenho anterior até o novo chegar
  });
  const operations = useQuery({
    queryKey: ["operations", projectId, service, environment, window],
    queryFn: () => api.serviceOperations(projectId, service, params),
    enabled,
    placeholderData: keepPreviousData,
  });
  const recent = useQuery({
    queryKey: ["traces", projectId, "recent", service, environment, window],
    queryFn: () => api.traces(projectId, { environment, through: service, limit: 8, ...window! }),
    enabled,
  });

  const points = metrics.data?.points.map((p) => ({ ...p, t: new Date(p.t).getTime() })) ?? [];
  const tracesLink = scoped(`/projects/${projectId}/traces?through=${encodeURIComponent(service)}`);
  const calledBy = snapshot?.edges.filter((e) => e.target === service) ?? [];
  const calls = snapshot?.edges.filter((e) => e.source === service) ?? [];
  const stale = status === "sem dados novos";

  return (
    <div className="space-y-4 px-4 pb-8 sm:px-6">
      <div className="flex flex-wrap items-center gap-3">
        <HealthLabel state={state} />
        {snapshot?.health[service] && (
          <span className="font-mono text-[11px] text-faint">{snapshot.health[service].reason}</span>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href={tracesLink}>Traces deste serviço</Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href={`${tracesLink}&status=error`}>Só os com erro</Link>
          </Button>
        </div>
      </div>

      {snapshot?.incident && involved(snapshot.incident, service) && (
        <IncidentBanner incident={snapshot.incident} projectId={projectId} />
      )}

      <div className={cn("transition-opacity", stale && "opacity-50")}>
        {live ? (
          <MetricStrip className="xl:grid-cols-4">
            <Metric label="Requisições/s" value={formatRate(live.rps)} detail="as que este serviço atendeu">
              <Sparkline values={live.series.map((p) => p.rps)} className="h-6 w-20" />
            </Metric>
            <Metric
              label="Taxa de erro"
              value={formatPercent(live.error_rate)}
              detail={live.error_rate >= ERROR_ALERT ? "acima do limite de 5%" : "respostas 5xx"}
              tone={live.error_rate >= ERROR_ALERT ? "warning" : undefined}
            />
            <Metric label="Disponibilidade" value={formatPercent(live.availability)} detail="atendidas sem falha" />
            <Metric label="Latência p95" value={ms(live.p95_ms)} detail={`p50 ${ms(live.p50_ms)} · p99 ${ms(live.p99_ms)}`}>
              <Sparkline values={live.series.map((p) => p.p95_ms ?? 0)} className="h-6 w-20" />
            </Metric>
          </MetricStrip>
        ) : status === "conectando" || status === "reconectando" ? (
          <Skeleton className="h-[74px] rounded-lg" />
        ) : (
          <LiveEmpty status={status}>
            Este serviço não atendeu nenhuma requisição no último minuto. O histórico abaixo mostra o período escolhido.
          </LiveEmpty>
        )}
      </div>

      <Panel
        title="Histórico"
        description={
          metrics.data
            ? `${RANGES[range].label} · um ponto a cada ${metrics.data.step_seconds >= 60 ? `${metrics.data.step_seconds / 60} min` : `${metrics.data.step_seconds} s`} · percentis exatos, sobre os spans gravados`
            : RANGES[range].label
        }
        bodyClassName="grid divide-y xl:grid-cols-3 xl:divide-x xl:divide-y-0"
      >
        <TimeSeries
          bare
          title="Requisições por segundo"
          data={points.map((p) => ({ t: p.t, rps: p.rps }))}
          series={[{ key: "rps", label: "req/s", color: "var(--primary)" }]}
          format={formatRate}
          height={170}
          dimmed={metrics.isPlaceholderData}
        />
        <TimeSeries
          bare
          title="Taxa de erro"
          data={points.map((p) => ({ t: p.t, erro: p.error_rate }))}
          series={[{ key: "erro", label: "erro", color: "var(--destructive)" }]}
          format={(v) => formatPercent(v)}
          threshold={{ value: ERROR_ALERT, label: "limite 5%" }}
          height={170}
          dimmed={metrics.isPlaceholderData}
        />
        <TimeSeries
          bare
          title="Latência"
          data={points.map((p) => ({ t: p.t, p50: p.p50_ms, p95: p.p95_ms, p99: p.p99_ms }))}
          series={[
            { key: "p50", label: "p50", color: PERCENTILE_COLORS.p50 },
            { key: "p95", label: "p95", color: PERCENTILE_COLORS.p95 },
            { key: "p99", label: "p99", color: PERCENTILE_COLORS.p99 },
          ]}
          format={formatDuration}
          height={170}
          dimmed={metrics.isPlaceholderData}
        />
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Panel title="Rotas atendidas" description={RANGES[range].label}>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Rota</TableHead>
                <TableHead className="text-right">Requisições</TableHead>
                <TableHead className="text-right">Erro</TableHead>
                <TableHead className="text-right">p50</TableHead>
                <TableHead className="text-right">p95</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {operations.data?.map((op) => (
                <TableRow key={`${op.http_method} ${op.operation}`}>
                  <TableCell className="font-mono text-xs">
                    {op.http_method && <span className="mr-2 text-faint">{op.http_method}</span>}
                    {op.operation}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">{op.requests.toLocaleString("pt-BR")}</TableCell>
                  <TableCell
                    className={cn("text-right font-mono text-xs tabular", op.error_rate >= ERROR_ALERT && "text-warning")}
                  >
                    {formatPercent(op.error_rate)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">{formatDuration(op.p50_ms)}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">{formatDuration(op.p95_ms)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {operations.isSuccess && operations.data.length === 0 && (
            <p className="px-3 py-6 text-[13px] text-muted-foreground">Nenhuma requisição neste período.</p>
          )}
        </Panel>

        <Panel title="Dependências" description="Ao vivo, medidas do lado de quem chama">
          <div className="grid grid-cols-[minmax(0,1fr)_56px_48px_60px] gap-2 border-b px-3 py-1.5 text-[11px] text-faint">
            <span>serviço</span>
            <span className="text-right">req/s</span>
            <span className="text-right">falha</span>
            <span className="text-right">p95</span>
          </div>
          <Dependencies title="Quem chama este serviço" icon={ArrowDownLeft} edges={calledBy} side="source" projectId={projectId} scoped={scoped} />
          <Dependencies title="O que este serviço chama" icon={ArrowUpRight} edges={calls} side="target" projectId={projectId} scoped={scoped} />
        </Panel>
      </div>

      <Panel
        title="Traces recentes"
        description="Os últimos que passaram por este serviço"
        actions={
          <Link href={tracesLink} className="text-xs text-primary hover:underline">
            Todos →
          </Link>
        }
      >
        {recent.isPending ? (
          <Skeleton className="m-3 h-24" />
        ) : recent.data && recent.data.traces.length > 0 ? (
          <ul className="divide-y">
            {recent.data.traces.map((t) => (
              <li key={t.trace_id}>
                <Link
                  href={`/projects/${projectId}/traces/${t.trace_id}?around=${encodeURIComponent(t.start_time)}`}
                  className="grid grid-cols-[72px_minmax(0,1fr)_80px_64px] items-center gap-3 px-3 py-1.5 font-mono text-xs transition-colors duration-75 hover:bg-accent/40"
                >
                  <span className="text-muted-foreground tabular">{formatClock(t.start_time).slice(0, 8)}</span>
                  <span className="truncate">
                    <span className="text-faint">{t.service} </span>
                    {t.name}
                  </span>
                  <span className="text-right tabular">{formatDuration(t.duration_ms)}</span>
                  <span className={cn("text-right", t.error_count ? "text-destructive" : "text-faint")}>
                    {t.error_count ? `${t.error_count} erro${t.error_count > 1 ? "s" : ""}` : "ok"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-3 py-6 text-[13px] text-muted-foreground">Nenhum trace passou por aqui neste período.</p>
        )}
      </Panel>
    </div>
  );
}

function Dependencies({
  title,
  icon: Icon,
  edges,
  side,
  projectId,
  scoped,
}: {
  title: string;
  icon: React.ElementType;
  edges: LiveEdge[];
  side: "source" | "target";
  projectId: number;
  scoped: (href: string) => string;
}) {
  return (
    <div className="border-b last:border-b-0">
      <h3 className="flex items-center gap-1.5 px-3 pt-2.5 pb-1 text-xs text-muted-foreground">
        <Icon className="size-3.5" /> {title}
      </h3>
      {edges.length === 0 ? (
        <p className="px-3 pb-2.5 text-xs text-faint">nenhum no último minuto</p>
      ) : (
        <ul className="pb-1.5">
          {edges.map((e) => {
            const other = e[side];
            return (
              <li key={`${e.source}>${e.target}`} className="grid grid-cols-[minmax(0,1fr)_56px_48px_60px] items-center gap-2 px-3 py-1 font-mono text-xs">
                {e.virtual && side === "target" ? (
                  <span className="truncate text-muted-foreground">{e.address} <span className="text-faint">externo</span></span>
                ) : (
                  <Link href={scoped(`/projects/${projectId}/services/${encodeURIComponent(other)}`)} className="truncate hover:text-primary">
                    {other}
                  </Link>
                )}
                <span className="text-right text-muted-foreground tabular">{formatRate(e.rps)}</span>
                <span className={cn("text-right tabular", e.error_rate >= ERROR_ALERT ? "text-warning" : "text-muted-foreground")}>
                  {formatPercent(e.error_rate)}
                </span>
                <span className="text-right text-muted-foreground tabular">{ms(e.p95_ms)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** O serviço está no incidente: é causa, foi afetado, está em risco ou uma rota afetada passa por ele. */
function involved(incident: LiveIncident, service: string): boolean {
  return (
    incident.causes.some((c) => c.node === service) ||
    incident.affected.some((a) => a.node === service) ||
    incident.at_risk.includes(service) ||
    incident.endpoints.some((e) => e.service === service)
  );
}

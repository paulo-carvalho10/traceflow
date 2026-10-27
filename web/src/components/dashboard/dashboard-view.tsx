"use client";

import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Sparkline } from "@/components/charts/sparkline";
import { TimeSeries } from "@/components/charts/time-series";
import { HealthDot, HealthLabel, serviceState } from "@/components/health";
import { IncidentBanner, SeverityBadge } from "@/components/incidents/badges";
import { LiveEmpty } from "@/components/live-controls";
import { Metric, MetricStrip, Panel } from "@/components/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RANGES, useWorkspace } from "@/components/workspace";
import { type IncidentSummary, type MetricSeries, api } from "@/lib/api";
import { formatAgo, formatDuration, formatPercent, formatRate } from "@/lib/format";
import { formatElapsed } from "@/lib/incidents";
import { ERROR_ALERT, type LiveService, type LiveSnapshot, type Severity } from "@/lib/live";
import { cn } from "@/lib/utils";

const ms = (v: number | null | undefined) => (v === null || v === undefined ? "–" : formatDuration(v));

/**
 * A visão geral: como o sistema está agora (a faixa de números e a saúde de cada serviço) e
 * como chegou até aqui (o tráfego, a latência e o erro da entrada no período, os incidentes).
 */
export function DashboardView() {
  const { projectId, environment, environments, environmentsLoading, live, window, range, scoped } = useWorkspace();
  const { snapshot, status } = live;
  const catalog = useQuery({
    queryKey: ["services", projectId, environment],
    queryFn: () => api.services(projectId, environment),
    enabled: environment !== undefined,
  });
  const incidents = useQuery({
    queryKey: ["incidents", projectId, "recent", environment],
    queryFn: () => api.incidents(projectId, { environment }),
    enabled: environment !== undefined,
    refetchInterval: 10_000,
  });
  const history = useEntryHistory(snapshot, projectId, environment, window);

  if (!environmentsLoading && environments.length === 0) {
    return (
      <p className="px-4 py-16 text-center text-[13px] text-muted-foreground sm:px-6">
        Nenhum span chegou a este projeto ainda. Crie uma chave de ingestão em Configurações e aponte a sua aplicação
        para a ingestão.
      </p>
    );
  }

  const entry = snapshot?.entry ?? null;
  const stale = status === "sem dados novos"; // números do último retrato: apagados, não são "o agora"
  const live_ = new Map(snapshot?.services.map((s) => [s.name, s]));
  const names = [...new Set([...(catalog.data?.map((s) => s.name) ?? []), ...live_.keys()])].sort();
  const states = names.map((n) => serviceState(n, snapshot));
  const unhealthy = states.filter((s) => s !== "healthy" && s !== "idle").length;
  const active = states.filter((s) => s !== "idle").length;
  const periodRequests = history.points.reduce((sum, p) => sum + p.requests, 0);

  return (
    <div className="space-y-4 px-4 pb-8 sm:px-6">
      {snapshot?.incident && <IncidentBanner incident={snapshot.incident} projectId={projectId} />}

      <section aria-label="Agora, na entrada" className={cn("transition-opacity", stale && "opacity-50")}>
        {entry ? (
          <MetricStrip>
            <Metric label="Requisições/s" value={formatRate(entry.rps)} detail="na entrada · último minuto">
              <Sparkline values={entry.series.map((p) => p.rps)} className="h-6 w-20" />
            </Metric>
            <Metric
              label="Requisições no período"
              value={history.loading ? "…" : periodRequests.toLocaleString("pt-BR")}
              detail={`${RANGES[range].label.toLowerCase()} · ${history.services.join(", ") || "entrada"}`}
            />
            <Metric
              label="Latência p95"
              value={ms(entry.p95_ms)}
              detail={`p50 ${ms(entry.p50_ms)} · p99 ${ms(entry.p99_ms)}`}
            />
            <Metric
              label="Taxa de erro"
              value={formatPercent(entry.error_rate)}
              detail={entry.error_rate >= ERROR_ALERT ? "acima do limite de 5%" : "respostas 5xx na entrada"}
              tone={entry.error_rate >= ERROR_ALERT ? "warning" : undefined}
            />
            <Metric
              label="Serviços ativos"
              value={`${active}/${names.length}`}
              detail={unhealthy ? `${unhealthy} fora do normal agora` : "todos saudáveis"}
              tone={unhealthy ? "warning" : undefined}
            />
          </MetricStrip>
        ) : status === "conectando" || status === "reconectando" ? (
          <Skeleton className="h-[74px] rounded-lg" />
        ) : (
          <LiveEmpty status={status}>
            Nenhuma requisição chegou a este ambiente no último minuto. Os números aparecem sozinhos quando chegar.
          </LiveEmpty>
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel
          title="A entrada do sistema"
          description={`${RANGES[range].label} · ${history.services.length ? history.services.join(", ") : "sem tráfego no período"}`}
          bodyClassName="divide-y"
        >
          {history.points.length ? (
            <>
              <TimeSeries
                bare
                title="Requisições por segundo"
                data={history.points.map((p) => ({ t: p.t, rps: p.rps }))}
                series={[{ key: "rps", label: "req/s", color: "var(--primary)" }]}
                format={formatRate}
                height={180}
                dimmed={history.fetching}
              />
              <div className="grid divide-y md:grid-cols-2 md:divide-x md:divide-y-0">
                <TimeSeries
                  bare
                  title="Latência p95"
                  data={history.points.map((p) => ({ t: p.t, p95: p.p95_ms }))}
                  series={[{ key: "p95", label: "p95", color: "var(--primary)" }]}
                  format={formatDuration}
                  height={150}
                  dimmed={history.fetching}
                />
                <TimeSeries
                  bare
                  title="Taxa de erro"
                  data={history.points.map((p) => ({ t: p.t, erro: p.error_rate }))}
                  series={[{ key: "erro", label: "erro", color: "var(--destructive)" }]}
                  format={formatPercent}
                  height={150}
                  threshold={{ value: ERROR_ALERT, label: "limite 5%" }}
                  dimmed={history.fetching}
                />
              </div>
            </>
          ) : history.loading ? (
            <Skeleton className="m-3 h-[340px]" />
          ) : (
            <p className="px-3 py-10 text-center text-[13px] text-muted-foreground">
              Sem requisições na entrada neste período.
            </p>
          )}
        </Panel>

        <div className="space-y-4">
          <RecentIncidents incidents={incidents.data} projectId={projectId} scoped={scoped} />
          <Anomalies snapshot={snapshot} projectId={projectId} scoped={scoped} />
        </div>
      </div>

      <Panel
        title="Saúde dos serviços"
        description="Janela ao vivo: os 10 s que terminam 3 s atrás"
        actions={
          <Link href={scoped(`/projects/${projectId}/services`)} className="text-xs text-primary hover:underline">
            Todos os serviços →
          </Link>
        }
        className={cn("transition-opacity", stale && "opacity-50")}
      >
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Serviço</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="text-right">Req/s</TableHead>
              <TableHead className="text-right">Erro</TableHead>
              <TableHead className="text-right">p50</TableHead>
              <TableHead className="text-right">p95</TableHead>
              <TableHead className="text-right">p99</TableHead>
              <TableHead className="w-32">Último minuto</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {names.map((name) => (
              <ServiceRow
                key={name}
                name={name}
                stats={live_.get(name)}
                state={serviceState(name, snapshot)}
                href={scoped(`/projects/${projectId}/services/${encodeURIComponent(name)}`)}
              />
            ))}
          </TableBody>
        </Table>
      </Panel>
    </div>
  );
}

/**
 * O histórico da entrada no período: a série dos serviços por onde as requisições entram
 * (no retrato ao vivo, os que têm rotas de entrada), somada ponto a ponto.
 */
function useEntryHistory(
  snapshot: LiveSnapshot | null,
  projectId: number,
  environment: string | undefined,
  window: { since: string; until: string } | null,
) {
  const services = [...new Set(snapshot?.entrypoints.map((e) => e.service) ?? [])].sort();
  const results = useQueries({
    queries: services.map((service) => ({
      queryKey: ["metrics", projectId, service, environment, window],
      queryFn: () => api.serviceMetrics(projectId, service, { environment, ...window! }),
      enabled: window !== null && environment !== undefined,
      placeholderData: keepPreviousData,
    })),
  });
  const series = results.map((r) => r.data).filter((d): d is MetricSeries => d !== undefined);
  const byTime = new Map<number, { t: number; requests: number; rps: number; errors: number; p95_ms: number | null }>();
  for (const s of series) {
    for (const p of s.points) {
      const t = new Date(p.t).getTime();
      const row = byTime.get(t) ?? { t, requests: 0, rps: 0, errors: 0, p95_ms: null };
      row.requests += p.requests;
      row.rps += p.rps;
      row.errors += (p.error_rate ?? 0) * p.requests;
      // com mais de uma porta de entrada, o p95 mostrado é o da mais lenta
      row.p95_ms = p.p95_ms === null ? row.p95_ms : Math.max(row.p95_ms ?? 0, p.p95_ms);
      byTime.set(t, row);
    }
  }
  const points = [...byTime.values()]
    .sort((a, b) => a.t - b.t)
    .map((r) => ({ ...r, error_rate: r.requests ? r.errors / r.requests : null }));
  return {
    services,
    points,
    loading: services.length > 0 && results.some((r) => r.isPending),
    fetching: results.some((r) => r.isFetching && r.isPlaceholderData),
  };
}

function RecentIncidents({
  incidents,
  projectId,
  scoped,
}: {
  incidents: IncidentSummary[] | undefined;
  projectId: number;
  scoped: (href: string) => string;
}) {
  const recent = incidents?.slice(0, 5);
  return (
    <Panel
      title="Incidentes recentes"
      actions={
        <Link href={scoped(`/projects/${projectId}/incidents`)} className="text-xs text-primary hover:underline">
          Todos →
        </Link>
      }
    >
      {!recent ? (
        <Skeleton className="m-3 h-24" />
      ) : recent.length === 0 ? (
        <p className="px-3 py-6 text-[13px] text-muted-foreground">Nenhum incidente neste ambiente.</p>
      ) : (
        <ul className="divide-y">
          {recent.map((i) => (
            <li key={i.id}>
              <Link
                href={`/projects/${projectId}/incidents/${i.id}`}
                className="block px-3 py-2 transition-colors duration-100 hover:bg-accent/50"
              >
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={(i.status === "open" ? i.severity : i.peak_severity) as Severity} />
                  <span className="min-w-0 flex-1 truncate text-[13px]">{i.title}</span>
                </div>
                <div className="mt-1 flex gap-2 font-mono text-[11px] text-faint">
                  {i.status === "open" ? (
                    <span className="text-destructive">aberto há {formatElapsed(i.opened_at)}</span>
                  ) : (
                    <span>
                      {formatAgo(i.opened_at)} · durou {formatElapsed(i.opened_at, i.resolved_at!)}
                    </span>
                  )}
                  <span className="truncate">· causa {i.causes.join(", ") || "–"}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** O que está fora do normal agora, com o motivo de cada um (a regra que disparou). */
function Anomalies({
  snapshot,
  projectId,
  scoped,
}: {
  snapshot: LiveSnapshot | null;
  projectId: number;
  scoped: (href: string) => string;
}) {
  const sick = Object.entries(snapshot?.health ?? {});
  return (
    <Panel title="Fora do normal agora">
      {sick.length === 0 ? (
        <p className="px-3 py-6 text-[13px] text-muted-foreground">
          {snapshot ? "Todos os serviços dentro das regras de detecção." : "Esperando o retrato ao vivo."}
        </p>
      ) : (
        <ul className="divide-y">
          {sick.map(([node, h]) => (
            <li key={node} className="px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <Link
                  href={scoped(`/projects/${projectId}/services/${encodeURIComponent(node)}`)}
                  className="truncate font-mono text-xs hover:text-primary"
                >
                  {node}
                </Link>
                <HealthLabel state={h.state} />
              </div>
              <p className="mt-0.5 font-mono text-[11px] text-faint">{h.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function ServiceRow({
  name,
  stats,
  state,
  href,
}: {
  name: string;
  stats: LiveService | undefined;
  state: ReturnType<typeof serviceState>;
  href: string;
}) {
  return (
    <TableRow>
      <TableCell>
        <Link href={href} className="flex items-center gap-2 font-mono text-xs hover:text-primary">
          <HealthDot state={state} />
          {name}
        </Link>
      </TableCell>
      <TableCell>
        <HealthLabel state={state} />
      </TableCell>
      {stats ? (
        <>
          <TableCell className="text-right font-mono text-xs tabular">{formatRate(stats.rps)}</TableCell>
          <TableCell
            className={cn("text-right font-mono text-xs tabular", stats.error_rate >= ERROR_ALERT && "text-warning")}
          >
            {formatPercent(stats.error_rate)}
          </TableCell>
          <TableCell className="text-right font-mono text-xs tabular">{ms(stats.p50_ms)}</TableCell>
          <TableCell className="text-right font-mono text-xs tabular">{ms(stats.p95_ms)}</TableCell>
          <TableCell className="text-right font-mono text-xs tabular">{ms(stats.p99_ms)}</TableCell>
          <TableCell>
            <Sparkline values={stats.series.map((p) => p.rps)} className="h-5 w-28" />
          </TableCell>
        </>
      ) : (
        <TableCell colSpan={6} className="text-xs text-faint">
          sem tráfego no último minuto
        </TableCell>
      )}
    </TableRow>
  );
}


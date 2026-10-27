"use client";

import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { TimeSeries } from "@/components/charts/time-series";
import { HealthDot, serviceState } from "@/components/health";
import { Panel } from "@/components/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RANGES, useWorkspace } from "@/components/workspace";
import { type MetricPoint, type MetricSeries, api } from "@/lib/api";
import { formatDuration, formatPercent, formatRate } from "@/lib/format";
import { ERROR_ALERT } from "@/lib/live";
import { cn } from "@/lib/utils";

type MetricKey = "rps" | "error_rate" | "p95_ms" | "p99_ms";

const METRICS: Record<MetricKey, { label: string; format: (v: number) => string; threshold?: number; floor?: number }> = {
  rps: { label: "Requisições/s", format: formatRate },
  error_rate: { label: "Taxa de erro", format: formatPercent, threshold: ERROR_ALERT, floor: ERROR_ALERT * 1.2 },
  p95_ms: { label: "Latência p95", format: formatDuration },
  p99_ms: { label: "Latência p99", format: formatDuration },
};

/**
 * As métricas de todos os serviços no período do cabeçalho, para comparar. Um gráfico pequeno
 * por serviço, todos na mesma escala (no lugar de várias linhas coloridas num gráfico só, que
 * exigiriam uma cor por serviço), e uma tabela com o resumo do período.
 */
export function MetricsView() {
  const { projectId, environment, window, range, live, scoped } = useWorkspace();
  const [metric, setMetric] = useState<MetricKey>("rps");
  const [shared, setShared] = useState(true);
  const catalog = useQuery({
    queryKey: ["services", projectId, environment],
    queryFn: () => api.services(projectId, environment),
    enabled: environment !== undefined,
  });
  const names = [...new Set(catalog.data?.map((s) => s.name) ?? [])].sort();
  const results = useQueries({
    queries: names.map((service) => ({
      queryKey: ["metrics", projectId, service, environment, window],
      queryFn: () => api.serviceMetrics(projectId, service, { environment, ...window! }),
      enabled: window !== null && environment !== undefined,
      placeholderData: keepPreviousData,
    })),
  });
  const series = results.map((r) => r.data).filter((d): d is MetricSeries => d !== undefined);
  const def = METRICS[metric];
  const top = Math.max(def.floor ?? 0, ...series.flatMap((s) => s.points.map((p) => p[metric] ?? 0)));

  return (
    <div className="space-y-4 px-4 pb-8 sm:px-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex h-7 overflow-hidden rounded-md border text-xs" role="group" aria-label="Métrica">
          {(Object.keys(METRICS) as MetricKey[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setMetric(key)}
              aria-pressed={metric === key}
              className={cn(
                "border-r px-2.5 transition-colors duration-100 last:border-r-0",
                metric === key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {METRICS[key].label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} className="accent-primary" />
          mesma escala em todos
        </label>
        <span className="ml-auto text-xs text-faint">
          {RANGES[range].label}
          {series[0] && ` · um ponto a cada ${series[0].step_seconds >= 60 ? `${series[0].step_seconds / 60} min` : `${series[0].step_seconds} s`}`}
        </span>
      </div>

      {catalog.isPending || (names.length > 0 && series.length === 0) ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-[190px] rounded-lg" />
          ))}
        </div>
      ) : names.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-10 text-center text-[13px] text-muted-foreground">
          Nenhum serviço mandou spans neste ambiente ainda.
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {series.map((s, i) => (
            <div key={s.service} className="relative">
              <Link
                href={scoped(`/projects/${projectId}/services/${encodeURIComponent(s.service)}`)}
                className="absolute top-2.5 right-10 z-10 flex items-center gap-1.5 font-mono text-[11px] text-faint hover:text-primary"
              >
                <HealthDot state={serviceState(s.service, live.snapshot)} /> abrir
              </Link>
              <TimeSeries
                title={s.service}
                data={s.points.map((p) => ({ t: new Date(p.t).getTime(), v: p[metric] }))}
                series={[{ key: "v", label: def.label, color: metric === "error_rate" ? "var(--destructive)" : "var(--primary)" }]}
                format={def.format}
                height={140}
                minMax={shared ? top : def.floor}
                threshold={def.threshold !== undefined ? { value: def.threshold, label: "limite 5%" } : undefined}
                dimmed={results[i]?.isPlaceholderData}
              />
            </div>
          ))}
        </div>
      )}

      {series.length > 0 && (
        <Panel title="Resumo do período" description="Calculado sobre os pontos do histórico">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Serviço</TableHead>
                <TableHead className="text-right">Requisições</TableHead>
                <TableHead className="text-right">Req/s média</TableHead>
                <TableHead className="text-right">Erro</TableHead>
                <TableHead className="text-right">p95 típico</TableHead>
                <TableHead className="text-right">p95 no pior momento</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {series.map((s) => {
                const sum = summarize(s.points, s.step_seconds);
                return (
                  <TableRow key={s.service}>
                    <TableCell>
                      <Link
                        href={scoped(`/projects/${projectId}/services/${encodeURIComponent(s.service)}`)}
                        className="flex items-center gap-2 font-mono text-xs hover:text-primary"
                      >
                        <HealthDot state={serviceState(s.service, live.snapshot)} />
                        {s.service}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular">{sum.requests.toLocaleString("pt-BR")}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular">{formatRate(sum.rps)}</TableCell>
                    <TableCell className={cn("text-right font-mono text-xs tabular", sum.errorRate >= ERROR_ALERT && "text-warning")}>
                      {formatPercent(sum.errorRate)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular">{sum.p95 === null ? "–" : formatDuration(sum.p95)}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular">{sum.worstP95 === null ? "–" : formatDuration(sum.worstP95)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <p className="border-t px-3 py-2 text-[11px] text-faint">
            “p95 típico” é a mediana dos p95 de cada ponto, ponderada pelo tráfego; percentis não se somam nem se tiram
            média, por isso não há um “p95 do período” exato aqui. Ele está na página de cada serviço, rota por rota.
          </p>
        </Panel>
      )}
    </div>
  );
}

/** O resumo de uma série: total, média, erro ponderado e um p95 típico (mediana ponderada). */
export function summarize(points: MetricPoint[], stepSeconds: number) {
  const requests = points.reduce((sum, p) => sum + p.requests, 0);
  const errors = points.reduce((sum, p) => sum + (p.error_rate ?? 0) * p.requests, 0);
  const withP95 = points.filter((p) => p.p95_ms !== null && p.requests > 0).sort((a, b) => a.p95_ms! - b.p95_ms!);
  let acc = 0;
  let p95: number | null = null;
  for (const p of withP95) {
    acc += p.requests;
    if (acc >= requests / 2) {
      p95 = p.p95_ms;
      break;
    }
  }
  return {
    requests,
    rps: points.length ? requests / (points.length * stepSeconds) : 0,
    errorRate: requests ? errors / requests : 0,
    p95,
    worstP95: withP95.length ? withP95[withP95.length - 1].p95_ms : null,
  };
}

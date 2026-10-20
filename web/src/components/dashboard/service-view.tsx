"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { StatTile } from "@/components/charts/stat-tile";
import { TimeSeries } from "@/components/charts/time-series";
import { EnvironmentSelect, LiveBadge, useEnvironment } from "@/components/live-controls";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useLive } from "@/hooks/use-live";
import { api } from "@/lib/api";
import { PERCENTILE_COLORS } from "@/lib/colors";
import { formatDuration, formatPercent, formatRate } from "@/lib/format";

const PERIODS = { "1h": 60, "6h": 360, "24h": 1440, "3d": 4320 } as const;
type Period = keyof typeof PERIODS;

export function ServiceView({ projectId, service }: { projectId: number; service: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const period = (params.get("period") as Period | null) ?? "1h";
  const { environment, environments, choose } = useEnvironment(projectId);
  const { snapshot, status } = useLive(projectId, environment);
  const live = snapshot?.services.find((s) => s.name === service);

  // O "agora" do histórico anda de 30 em 30 s: a chave da consulta muda e ela é refeita
  const timeWindow = useQuery({
    queryKey: ["window", period],
    queryFn: () => {
      const until = new Date();
      return { until: until.toISOString(), since: new Date(until.getTime() - PERIODS[period] * 60_000).toISOString() };
    },
    refetchInterval: 30_000,
    staleTime: 0,
  });
  const range = { environment, ...(timeWindow.data ?? { since: "", until: "" }) };
  const enabled = timeWindow.isSuccess && environment !== undefined;
  const metrics = useQuery({
    queryKey: ["metrics", projectId, service, range],
    queryFn: () => api.serviceMetrics(projectId, service, range),
    enabled,
    placeholderData: keepPreviousData, // trocar o período mantém o desenho anterior até o novo chegar
  });
  const operations = useQuery({
    queryKey: ["operations", projectId, service, range],
    queryFn: () => api.serviceOperations(projectId, service, range),
    enabled,
    placeholderData: keepPreviousData,
  });

  const points = metrics.data?.points.map((p) => ({ ...p, t: new Date(p.t).getTime() })) ?? [];
  const tracesLink = `/projects/${projectId}/traces?through=${encodeURIComponent(service)}${
    environment ? `&environment=${encodeURIComponent(environment)}` : ""
  }`;

  function setPeriod(value: string) {
    const next = new URLSearchParams(params);
    if (value === "1h") next.delete("period");
    else next.set("period", value);
    router.replace(`${pathname}?${next}`, { scroll: false });
  }

  return (
    <div className="space-y-6 px-8 py-6">
      <div className="flex flex-wrap items-center gap-3">
        <EnvironmentSelect value={environment} options={environments} onChange={choose} />
        <Select value={period} onValueChange={setPeriod}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="1h">Histórico: 1 hora</SelectItem>
            <SelectItem value="6h">Histórico: 6 horas</SelectItem>
            <SelectItem value="24h">Histórico: 24 horas</SelectItem>
            <SelectItem value="3d">Histórico: 3 dias</SelectItem>
          </SelectContent>
        </Select>
        <LiveBadge status={status} />
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href={tracesLink}>
              Traces que passaram por aqui <ArrowRight className="size-3.5" />
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href={`${tracesLink}&status=error`}>Só os com erro</Link>
          </Button>
        </div>
      </div>

      <section aria-label="Agora" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {live ? (
          <>
            <StatTile
              label="Requisições por segundo"
              value={formatRate(live.rps)}
              hint="as que este serviço atendeu"
              trend={live.series.map((p) => p.rps)}
            />
            <StatTile
              label="Taxa de erro"
              value={formatPercent(live.error_rate)}
              hint="respostas de falha do sistema (5xx)"
              trend={live.series.map((p) => (p.rps ? p.errors / p.rps : 0))}
              alert={live.error_rate >= 0.05 ? "acima de 5%" : undefined}
            />
            <StatTile
              label="Disponibilidade"
              value={formatPercent(live.availability)}
              hint="requisições atendidas sem falha"
              trend={live.series.map((p) => (p.rps ? 1 - p.errors / p.rps : 1))}
            />
            <StatTile
              label="Latência p95"
              value={live.p95_ms === null ? "–" : formatDuration(live.p95_ms)}
              hint={`p50 ${live.p50_ms === null ? "–" : formatDuration(live.p50_ms)} · p99 ${
                live.p99_ms === null ? "–" : formatDuration(live.p99_ms)
              }`}
              trend={live.series.map((p) => p.p95_ms ?? 0)}
            />
          </>
        ) : status === "ao vivo" || status === "sem dados novos" ? (
          <p className="col-span-full rounded-xl border bg-card px-4 py-6 text-sm text-muted-foreground">
            Este serviço não atendeu nenhuma requisição no último minuto.
          </p>
        ) : (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[118px] rounded-xl" />)
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <TimeSeries
          title="Requisições por segundo"
          data={points.map((p) => ({ t: p.t, rps: p.rps }))}
          series={[{ key: "rps", label: "req/s", color: "var(--primary)" }]}
          format={formatRate}
          dimmed={metrics.isPlaceholderData}
        />
        <TimeSeries
          title="Taxa de erro"
          data={points.map((p) => ({ t: p.t, erro: p.error_rate }))}
          series={[{ key: "erro", label: "erro", color: "var(--primary)" }]}
          format={(v) => formatPercent(v)}
          minMax={0.05}
          dimmed={metrics.isPlaceholderData}
        />
        <TimeSeries
          title="Latência"
          data={points.map((p) => ({ t: p.t, p50: p.p50_ms, p95: p.p95_ms, p99: p.p99_ms }))}
          series={[
            { key: "p50", label: "p50", color: PERCENTILE_COLORS.p50 },
            { key: "p95", label: "p95", color: PERCENTILE_COLORS.p95 },
            { key: "p99", label: "p99", color: PERCENTILE_COLORS.p99 },
          ]}
          format={formatDuration}
          dimmed={metrics.isPlaceholderData}
        />
      </div>
      {metrics.data && (
        <p className="-mt-3 text-xs text-muted-foreground">
          Um ponto a cada {metrics.data.step_seconds >= 60 ? `${metrics.data.step_seconds / 60} min` : `${metrics.data.step_seconds} s`}.
          No histórico os percentis são exatos (calculados sobre os spans gravados); ao vivo, vêm de histogramas (erro abaixo de 10%).
        </p>
      )}

      <section className="rounded-xl border bg-card">
        <h2 className="px-4 pt-4 pb-2 text-sm font-medium">Rotas atendidas no período</h2>
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
                <TableCell className="font-mono text-[13px]">
                  {op.http_method && <span className="mr-2 text-muted-foreground">{op.http_method}</span>}
                  {op.operation}
                </TableCell>
                <TableCell className="text-right font-mono text-xs tabular">
                  {op.requests.toLocaleString("pt-BR")}
                </TableCell>
                <TableCell className="text-right font-mono text-xs tabular">{formatPercent(op.error_rate)}</TableCell>
                <TableCell className="text-right font-mono text-xs tabular">{formatDuration(op.p50_ms)}</TableCell>
                <TableCell className="text-right font-mono text-xs tabular">{formatDuration(op.p95_ms)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {operations.isSuccess && operations.data.length === 0 && (
          <p className="px-4 pb-4 text-sm text-muted-foreground">Nenhuma requisição neste período.</p>
        )}
      </section>
    </div>
  );
}

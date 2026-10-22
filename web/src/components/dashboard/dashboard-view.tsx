"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Sparkline } from "@/components/charts/sparkline";
import { StatTile } from "@/components/charts/stat-tile";
import { TimeSeries } from "@/components/charts/time-series";
import { EnvironmentSelect, LiveBadge, LiveEmpty, useEnvironment } from "@/components/live-controls";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useLive } from "@/hooks/use-live";
import { api } from "@/lib/api";
import { serviceColor } from "@/lib/colors";
import { formatDuration, formatPercent, formatRate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ERROR_ALERT, type LiveService, type LiveStats } from "@/lib/live";


export function DashboardView({ projectId }: { projectId: number }) {
  const { environment, environments, loading, choose } = useEnvironment(projectId);
  const { snapshot, status } = useLive(projectId, environment);
  const catalog = useQuery({
    queryKey: ["services", projectId, environment],
    queryFn: () => api.services(projectId, environment),
    enabled: environment !== undefined,
  });

  const live = new Map(snapshot?.services.map((s) => [s.name, s]));
  // serviços do catálogo sem tráfego no último minuto também aparecem: "parado" é informação
  const names = [...new Set([...(catalog.data?.map((s) => s.name) ?? []), ...live.keys()])].sort();
  const entry = snapshot?.entry ?? null;
  // sem sinal do processamento, os números são do último retrato que chegou: ficam apagados,
  // para ninguém lê-los como "o agora" (a etiqueta diz o motivo)
  const stale = status === "sem dados novos";

  if (!loading && environments.length === 0) {
    return (
      <p className="px-8 py-16 text-center text-sm text-muted-foreground">
        Nenhum span chegou a este projeto ainda. Crie uma chave de ingestão e configure a sua aplicação.
      </p>
    );
  }

  return (
    <div className="space-y-6 px-8 py-6">
      <div className="flex flex-wrap items-center gap-3">
        <EnvironmentSelect value={environment} options={environments} onChange={choose} />
        <LiveBadge status={status} />
      </div>

      <section
        aria-label="A entrada do sistema"
        className={cn("grid gap-4 transition-opacity sm:grid-cols-2 xl:grid-cols-4", stale && "opacity-50")}
      >
        {entry ? (
          <EntryTiles entry={entry} />
        ) : status === "conectando" || status === "reconectando" ? (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[118px] rounded-xl" />)
        ) : (
          <LiveEmpty status={status}>
            {status === "sem tráfego"
              ? "Nenhuma requisição chegou a este ambiente no último minuto. Assim que chegar, os números aparecem aqui sozinhos."
              : "Nenhuma requisição começou neste ambiente no último minuto. Os serviços que atenderam chamadas estão na tabela abaixo."}
          </LiveEmpty>
        )}
      </section>

      {entry && (
        <div className="grid gap-4 lg:grid-cols-2">
          <TimeSeries
            title="Requisições por segundo, na entrada"
            data={entry.series.map((p) => ({ t: p.t * 1000, rps: p.rps }))}
            series={[{ key: "rps", label: "req/s", color: "var(--primary)" }]}
            format={formatRate}
            dimmed={stale}
          />
          <TimeSeries
            title="p95 da entrada, nos últimos 10 s de cada instante"
            data={entry.series.map((p) => ({ t: p.t * 1000, p95: p.p95_ms }))}
            series={[{ key: "p95", label: "p95", color: "var(--primary)" }]}
            format={formatDuration}
            dimmed={stale}
          />
        </div>
      )}

      <section className={cn("rounded-xl border bg-card transition-opacity", stale && "opacity-50")}>
        <header className="flex items-baseline justify-between px-4 pt-4 pb-2">
          <h2 className="text-sm font-medium">Serviços</h2>
          <p className="text-xs text-muted-foreground">
            Janela: os 10 s que terminam 3 s atrás (dá tempo de os lotes atrasados chegarem)
          </p>
        </header>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Serviço</TableHead>
              <TableHead className="text-right">Req/s</TableHead>
              <TableHead className="text-right">Erro</TableHead>
              <TableHead className="text-right">Disponibilidade</TableHead>
              <TableHead className="text-right">p50</TableHead>
              <TableHead className="text-right">p95</TableHead>
              <TableHead className="text-right">p99</TableHead>
              <TableHead className="w-36">Último minuto</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {names.map((name) => (
              <ServiceRow key={name} name={name} stats={live.get(name)} projectId={projectId} environment={environment} />
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}

function EntryTiles({ entry }: { entry: LiveStats }) {
  const errorTrend = entry.series.map((p) => (p.rps ? p.errors / p.rps : 0));
  return (
    <>
      <StatTile
        label="Requisições por segundo"
        value={formatRate(entry.rps)}
        hint="na entrada, cada requisição uma vez"
        trend={entry.series.map((p) => p.rps)}
      />
      <StatTile
        label="Taxa de erro"
        value={formatPercent(entry.error_rate)}
        hint="respostas de falha do sistema (5xx)"
        trend={errorTrend}
        alert={entry.error_rate >= ERROR_ALERT ? "acima de 5%" : undefined}
      />
      <StatTile
        label="Disponibilidade"
        value={formatPercent(entry.availability)}
        hint="requisições atendidas sem falha"
        trend={entry.series.map((p) => (p.rps ? 1 - p.errors / p.rps : 1))}
      />
      <StatTile
        label="Latência p95"
        value={entry.p95_ms === null ? "–" : formatDuration(entry.p95_ms)}
        hint={`p50 ${entry.p50_ms === null ? "–" : formatDuration(entry.p50_ms)} · p99 ${
          entry.p99_ms === null ? "–" : formatDuration(entry.p99_ms)
        }`}
        trend={entry.series.map((p) => p.p95_ms ?? 0)}
      />
    </>
  );
}

function ServiceRow({
  name,
  stats,
  projectId,
  environment,
}: {
  name: string;
  stats: LiveService | undefined;
  projectId: number;
  environment: string | undefined;
}) {
  const href = `/projects/${projectId}/services/${encodeURIComponent(name)}${
    environment ? `?environment=${encodeURIComponent(environment)}` : ""
  }`;
  const ms = (v: number | null | undefined) => (v === null || v === undefined ? "–" : formatDuration(v));
  return (
    <TableRow>
      <TableCell>
        <Link href={href} className="flex items-center gap-2 font-medium hover:text-primary">
          <span className="size-2 rounded-full" style={{ background: serviceColor(name) }} />
          {name}
        </Link>
      </TableCell>
      {stats ? (
        <>
          <TableCell className="text-right font-mono text-xs tabular">{formatRate(stats.rps)}</TableCell>
          <TableCell
            className={`text-right font-mono text-xs tabular ${stats.error_rate >= ERROR_ALERT ? "text-warning" : ""}`}
          >
            {formatPercent(stats.error_rate)}
          </TableCell>
          <TableCell className="text-right font-mono text-xs tabular">{formatPercent(stats.availability)}</TableCell>
          <TableCell className="text-right font-mono text-xs tabular">{ms(stats.p50_ms)}</TableCell>
          <TableCell className="text-right font-mono text-xs tabular">{ms(stats.p95_ms)}</TableCell>
          <TableCell className="text-right font-mono text-xs tabular">{ms(stats.p99_ms)}</TableCell>
          <TableCell>
            <Sparkline values={stats.series.map((p) => p.rps)} className="h-6 w-32" />
          </TableCell>
        </>
      ) : (
        <TableCell colSpan={7} className="text-xs text-muted-foreground">
          sem tráfego no último minuto
        </TableCell>
      )}
    </TableRow>
  );
}

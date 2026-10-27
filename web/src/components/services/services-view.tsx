"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Sparkline } from "@/components/charts/sparkline";
import { HealthDot, HealthLabel, type ServiceState, serviceState } from "@/components/health";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useWorkspace } from "@/components/workspace";
import { api } from "@/lib/api";
import { formatAgo, formatDuration, formatPercent, formatRate } from "@/lib/format";
import { ERROR_ALERT, type LiveService } from "@/lib/live";
import { cn } from "@/lib/utils";

type Row = {
  name: string;
  environment: string;
  state: ServiceState;
  stats: LiveService | undefined;
  lastSeen: string | undefined;
};
type SortKey = "name" | "state" | "rps" | "p50" | "p95" | "error" | "seen";
type StateFilter = "todos" | "fora" | "parados";

// a ordem de "estado": o que pede atenção primeiro
const STATE_ORDER: Record<ServiceState, number> = { unresponsive: 0, failing: 1, degraded: 2, healthy: 3, idle: 4 };

/**
 * Os serviços monitorados no ambiente: a saúde e os números do último minuto (ao vivo) e a
 * última vez que cada um mandou spans (o catálogo). Filtra pelo nome e pelo estado, e ordena
 * por qualquer coluna.
 */
export function ServicesView() {
  const router = useRouter();
  const { projectId, environment, live, scoped } = useWorkspace();
  const [text, setText] = useState("");
  const [only, setOnly] = useState<StateFilter>("todos");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "state", desc: false });
  const catalog = useQuery({
    queryKey: ["services", projectId, environment],
    queryFn: () => api.services(projectId, environment),
    enabled: environment !== undefined,
    refetchInterval: 30_000,
  });

  const stats = new Map(live.snapshot?.services.map((s) => [s.name, s]));
  const names = [...new Set([...(catalog.data?.map((s) => s.name) ?? []), ...stats.keys()])];
  const rows: Row[] = names.map((name) => ({
    name,
    environment: environment ?? "",
    state: serviceState(name, live.snapshot),
    stats: stats.get(name),
    lastSeen: catalog.data?.find((s) => s.name === name)?.last_seen,
  }));
  const counts = {
    todos: rows.length,
    fora: rows.filter((r) => r.state !== "healthy" && r.state !== "idle").length,
    parados: rows.filter((r) => r.state === "idle").length,
  };
  const value = (r: Row): number | string => {
    switch (sort.key) {
      case "name": return r.name;
      case "state": return STATE_ORDER[r.state];
      case "rps": return r.stats?.rps ?? -1;
      case "p50": return r.stats?.p50_ms ?? -1;
      case "p95": return r.stats?.p95_ms ?? -1;
      case "error": return r.stats?.error_rate ?? -1;
      case "seen": return r.lastSeen ? new Date(r.lastSeen).getTime() : 0;
    }
  };
  const visible = rows
    .filter((r) => r.name.toLowerCase().includes(text.trim().toLowerCase()))
    .filter((r) => (only === "fora" ? r.state !== "healthy" && r.state !== "idle" : only === "parados" ? r.state === "idle" : true))
    .sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      const order = typeof x === "string" ? x.localeCompare(String(y)) : x - (y as number);
      return (sort.desc ? -order : order) || a.name.localeCompare(b.name);
    });

  function header(key: SortKey, label: string, right = false) {
    const active = sort.key === key;
    const Arrow = sort.desc ? ArrowDown : ArrowUp;
    return (
      <TableHead className={cn(right && "text-right")} aria-sort={active ? (sort.desc ? "descending" : "ascending") : undefined}>
        <button
          type="button"
          onClick={() => setSort({ key, desc: active ? !sort.desc : key !== "name" && key !== "state" })}
          className={cn("inline-flex items-center gap-1 hover:text-foreground", active && "text-foreground")}
        >
          {label}
          {active && <Arrow className="size-3" />}
        </button>
      </TableHead>
    );
  }

  const ms = (v: number | null | undefined) => (v === null || v === undefined ? "–" : formatDuration(v));

  return (
    <div className="space-y-3 px-4 pb-8 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-faint" />
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Filtrar pelo nome"
            className="h-7 w-56 pl-7 font-mono text-xs"
            aria-label="Filtrar serviços pelo nome"
          />
        </div>
        <div className="inline-flex h-7 overflow-hidden rounded-md border text-xs" role="group" aria-label="Filtrar pelo estado">
          {(
            [
              ["todos", "Todos"],
              ["fora", "Fora do normal"],
              ["parados", "Sem tráfego"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setOnly(key)}
              aria-pressed={only === key}
              className={cn(
                "flex items-center gap-1.5 border-r px-2.5 transition-colors duration-100 last:border-r-0",
                only === key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
              <span className="font-mono text-[11px] text-faint">{counts[key]}</span>
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-faint">números do último minuto · janela de 10 s que termina 3 s atrás</span>
      </div>

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {header("name", "Serviço")}
              <TableHead>Ambiente</TableHead>
              {header("state", "Estado")}
              {header("rps", "Req/s", true)}
              {header("p50", "p50", true)}
              {header("p95", "p95", true)}
              {header("error", "Erro", true)}
              <TableHead className="w-28">Último minuto</TableHead>
              {header("seen", "Última atividade", true)}
            </TableRow>
          </TableHeader>
          <TableBody>
            {catalog.isPending &&
              Array.from({ length: 5 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={9}>
                    <Skeleton className="h-4 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {visible.map((r) => {
              const href = scoped(`/projects/${projectId}/services/${encodeURIComponent(r.name)}`);
              return (
                <TableRow
                  key={r.name}
                  className="cursor-pointer"
                  tabIndex={0}
                  onClick={() => router.push(href)}
                  onKeyDown={(e) => e.key === "Enter" && router.push(href)}
                >
                  <TableCell>
                    <span className="flex items-center gap-2 font-mono text-xs">
                      <HealthDot state={r.state} />
                      {r.name}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{r.environment}</TableCell>
                  <TableCell>
                    <HealthLabel state={r.state} />
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">{r.stats ? formatRate(r.stats.rps) : "–"}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">{ms(r.stats?.p50_ms)}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">{ms(r.stats?.p95_ms)}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-mono text-xs tabular",
                      r.stats && r.stats.error_rate >= ERROR_ALERT && "text-warning",
                    )}
                  >
                    {r.stats ? formatPercent(r.stats.error_rate) : "–"}
                  </TableCell>
                  <TableCell>
                    {r.stats && <Sparkline values={r.stats.series.map((p) => p.rps)} className="h-5 w-24" />}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground tabular">
                    {r.lastSeen ? formatAgo(r.lastSeen) : "–"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {catalog.isSuccess && visible.length === 0 && (
          <p className="px-6 py-12 text-center text-[13px] text-muted-foreground">
            {rows.length === 0 ? "Nenhum serviço mandou spans neste ambiente ainda." : "Nenhum serviço com esse filtro."}
          </p>
        )}
      </div>
    </div>
  );
}

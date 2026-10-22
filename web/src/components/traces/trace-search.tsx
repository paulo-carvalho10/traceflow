"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type TraceFilters, type TraceSummary, api } from "@/lib/api";
import { serviceColor } from "@/lib/colors";
import { formatAgo, formatClock, formatDuration } from "@/lib/format";

const PERIODS = { "15m": 15, "1h": 60, "6h": 360, "24h": 1440, "3d": 4320 } as const;
type Period = keyof typeof PERIODS;
const ALL = "__todos"; // o Select não aceita valor vazio: este representa "sem filtro"

/**
 * A busca de traces. Os filtros vivem na URL (?status=error&period=1h): um link copiado abre
 * a mesma busca, e o "voltar" do navegador desfaz um filtro.
 */
export function TraceSearch({ projectId }: { projectId: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const period = (params.get("period") as Period | null) ?? "1h";
  const filters: TraceFilters = {
    environment: params.get("environment") ?? undefined,
    service: params.get("service") ?? undefined,
    through: params.get("through") ?? undefined,
    operation: params.get("operation") ?? undefined,
    status: (params.get("status") as TraceFilters["status"]) ?? undefined,
    min_duration_ms: params.get("min") ? Number(params.get("min")) : undefined,
  };

  // O "agora" da busca fica congelado até alguém clicar em Atualizar: assim as páginas
  // seguintes (cursor) pertencem à mesma janela de tempo da primeira.
  const [snapshot, setSnapshot] = useState(() => Date.now());

  const environments = useQuery({
    queryKey: ["environments", projectId],
    queryFn: () => api.environments(projectId),
  });
  const services = useQuery({
    queryKey: ["services", projectId, filters.environment],
    queryFn: () => api.services(projectId, filters.environment),
  });
  const serviceNames = useMemo(
    () => [...new Set(services.data?.map((s) => s.name))].sort(),
    [services.data],
  );

  const traces = useInfiniteQuery({
    queryKey: ["traces", projectId, filters, period, snapshot],
    queryFn: ({ pageParam }) =>
      api.traces(projectId, {
        ...filters,
        since: new Date(snapshot - PERIODS[period] * 60_000).toISOString(),
        until: new Date(snapshot).toISOString(),
        cursor: pageParam,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = traces.data?.pages.flatMap((p) => p.traces) ?? [];
  const slowest = Math.max(1, ...rows.map((r) => r.duration_ms));

  function setFilter(name: string, value: string | undefined) {
    const next = new URLSearchParams(params);
    if (value === undefined || value === "" || value === ALL) next.delete(name);
    else next.set(name, value);
    if (name === "environment") {
      next.delete("service"); // o serviço pode não existir no outro ambiente
      next.delete("through");
    }
    router.replace(`${pathname}?${next}`, { scroll: false });
  }

  return (
    <div className="space-y-4 px-4 py-5 sm:px-8 sm:py-6">
      <div className="flex flex-wrap items-center gap-2">
        <FilterSelect
          label="Ambiente"
          value={filters.environment}
          onChange={(v) => setFilter("environment", v)}
          options={environments.data?.map((e) => e.name) ?? []}
        />
        <FilterSelect
          label="Entrou por"
          value={filters.service}
          onChange={(v) => setFilter("service", v)}
          options={serviceNames}
        />
        <FilterSelect
          label="Passou por"
          value={filters.through}
          onChange={(v) => setFilter("through", v)}
          options={serviceNames}
        />
        <Select value={filters.status ?? ALL} onValueChange={(v) => setFilter("status", v)}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos os status</SelectItem>
            <SelectItem value="error">Com erro</SelectItem>
            <SelectItem value="ok">Sem erro</SelectItem>
          </SelectContent>
        </Select>
        <Select value={period} onValueChange={(v) => setFilter("period", v === "1h" ? undefined : v)}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="15m">Últimos 15 min</SelectItem>
            <SelectItem value="1h">Última hora</SelectItem>
            <SelectItem value="6h">Últimas 6 h</SelectItem>
            <SelectItem value="24h">Últimas 24 h</SelectItem>
            <SelectItem value="3d">Últimos 3 dias</SelectItem>
          </SelectContent>
        </Select>
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const next = new URLSearchParams(params);
            for (const key of ["operation", "min"]) {
              const value = String(data.get(key) ?? "").trim();
              if (value) next.set(key, value);
              else next.delete(key);
            }
            router.replace(`${pathname}?${next}`, { scroll: false });
          }}
        >
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              name="operation"
              defaultValue={filters.operation}
              placeholder="Operação, ex.: /checkout"
              className="w-56 pl-8"
            />
          </div>
          <Input
            name="min"
            type="number"
            min={0}
            defaultValue={filters.min_duration_ms}
            placeholder="Duração mín. (ms)"
            className="w-40"
          />
          <Button type="submit" variant="secondary">
            Filtrar
          </Button>
        </form>
        <Button variant="ghost" size="icon" onClick={() => setSnapshot(Date.now())} aria-label="Atualizar">
          <RefreshCw className={traces.isFetching ? "size-4 animate-spin" : "size-4"} />
        </Button>
      </div>

      <div className="rounded-xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-28">Quando</TableHead>
              <TableHead>Operação</TableHead>
              <TableHead className="w-64">Duração</TableHead>
              <TableHead className="w-20 text-right">Spans</TableHead>
              <TableHead className="w-24 text-right">Serviços</TableHead>
              <TableHead className="w-28">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {traces.isPending &&
              Array.from({ length: 8 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {rows.map((trace) => (
              <TraceRow key={trace.trace_id} trace={trace} projectId={projectId} slowest={slowest} />
            ))}
          </TableBody>
        </Table>
        {traces.isSuccess && rows.length === 0 && (
          <div className="px-6 py-16 text-center text-sm text-muted-foreground">
            Nenhum trace com esses filtros neste período.
            <br />
            Tente um período maior ou tire algum filtro.
          </div>
        )}
        {traces.isError && (
          <div className="flex items-center justify-center gap-2 px-6 py-16 text-sm text-destructive">
            <AlertTriangle className="size-4" /> {traces.error.message}
          </div>
        )}
      </div>

      {traces.hasNextPage && (
        <div className="flex justify-center">
          <Button variant="outline" onClick={() => traces.fetchNextPage()} disabled={traces.isFetchingNextPage}>
            {traces.isFetchingNextPage ? "Carregando…" : "Carregar mais"}
          </Button>
        </div>
      )}
    </div>
  );
}

function TraceRow({ trace, projectId, slowest }: { trace: TraceSummary; projectId: number; slowest: number }) {
  const href = `/projects/${projectId}/traces/${trace.trace_id}?around=${encodeURIComponent(trace.start_time)}`;
  const failed = trace.error_count > 0;
  return (
    <TableRow className="cursor-pointer">
      <TableCell className="text-muted-foreground">
        <Tooltip>
          <TooltipTrigger asChild>
            <Link href={href} className="font-mono text-xs tabular">
              {formatClock(trace.start_time).slice(0, 8)}
            </Link>
          </TooltipTrigger>
          <TooltipContent>{formatAgo(trace.start_time)}</TooltipContent>
        </Tooltip>
      </TableCell>
      <TableCell>
        <Link href={href} className="flex min-w-0 items-center gap-2">
          <span className="size-2 shrink-0 rounded-full" style={{ background: serviceColor(trace.service) }} />
          <span className="text-muted-foreground">{trace.service}</span>
          <span className="truncate font-mono text-[13px]">{trace.name}</span>
        </Link>
      </TableCell>
      <TableCell>
        <Link href={href} className="flex items-center gap-3">
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <span
              className={failed ? "block h-full bg-destructive" : "block h-full bg-primary"}
              style={{ width: `${Math.max(2, (trace.duration_ms / slowest) * 100)}%` }}
            />
          </span>
          <span className="w-16 text-right font-mono text-xs tabular">{formatDuration(trace.duration_ms)}</span>
        </Link>
      </TableCell>
      <TableCell className="text-right font-mono text-xs tabular">{trace.span_count}</TableCell>
      <TableCell className="text-right font-mono text-xs tabular">{trace.service_count}</TableCell>
      <TableCell>
        {failed ? (
          <Badge variant="destructive">
            {trace.error_count} {trace.error_count === 1 ? "erro" : "erros"}
          </Badge>
        ) : (
          <Badge variant="secondary" className="text-success">
            ok
          </Badge>
        )}
        {trace.http_status_code && <HttpCode code={trace.http_status_code} />}
      </TableCell>
    </TableRow>
  );
}

/** 2xx discreto; 4xx em âmbar (o pedido foi recusado); 5xx em vermelho (o sistema falhou). */
export function HttpCode({ code }: { code: number }) {
  const tone = code >= 500 ? "text-destructive" : code >= 400 ? "text-warning" : "text-muted-foreground";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={`ml-2 font-mono text-xs ${tone}`}>{code}</span>
      </TooltipTrigger>
      <TooltipContent>
        {code >= 500
          ? "Falha do sistema (5xx)"
          : code >= 400
            ? "Pedido recusado (4xx): produto inexistente, pagamento recusado..."
            : "Sucesso"}
      </TooltipContent>
    </Tooltip>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | undefined;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <Select value={value ?? ALL} onValueChange={onChange}>
      <SelectTrigger className="w-52">
        {/* o rótulo fica no botão mesmo com um valor escolhido: "payments" sozinho não diz se
            o filtro é "entrou por" ou "passou por" */}
        <SelectValue placeholder={label}>{`${label}: ${value ?? "todos"}`}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{label}: todos</SelectItem>
        {options.map((option) => (
          <SelectItem key={option} value={option}>
            {option}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

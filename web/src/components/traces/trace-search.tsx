"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { TraceView } from "@/components/traces/trace-view";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { RANGES, useWorkspace } from "@/components/workspace";
import { type TraceFilters, type TraceSummary, api } from "@/lib/api";
import { formatAgo, formatClock, formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

const ALL = "__todos"; // o Select não aceita valor vazio: este representa "sem filtro"

/**
 * A busca de traces. O ambiente e o período vêm do cabeçalho; os filtros desta tela ficam na
 * URL (?status=error&through=payments), então um link copiado abre a mesma busca e o "voltar"
 * do navegador desfaz um filtro. Um trace escolhido abre ao lado (?trace=), sem sair da lista.
 */
export function TraceSearch() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { projectId, environment, range } = useWorkspace();
  const filters: TraceFilters = {
    environment,
    service: params.get("service") ?? undefined,
    through: params.get("through") ?? undefined,
    operation: params.get("operation") ?? undefined,
    status: (params.get("status") as TraceFilters["status"]) ?? undefined,
    min_duration_ms: params.get("min") ? Number(params.get("min")) : undefined,
  };
  const open = params.get("trace");

  // O "agora" da busca fica parado até alguém clicar em Atualizar: assim as páginas seguintes
  // (cursor) pertencem à mesma janela de tempo da primeira.
  const [now, setNow] = useState(() => Date.now());

  const services = useQuery({
    queryKey: ["services", projectId, environment],
    queryFn: () => api.services(projectId, environment),
    enabled: environment !== undefined,
  });
  const serviceNames = useMemo(() => [...new Set(services.data?.map((s) => s.name))].sort(), [services.data]);

  const traces = useInfiniteQuery({
    queryKey: ["traces", projectId, filters, range, now],
    queryFn: ({ pageParam }) =>
      api.traces(projectId, {
        ...filters,
        since: new Date(now - RANGES[range].minutes * 60_000).toISOString(),
        until: new Date(now).toISOString(),
        cursor: pageParam,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: environment !== undefined,
  });
  const rows = traces.data?.pages.flatMap((p) => p.traces) ?? [];
  const slowest = Math.max(1, ...rows.map((r) => r.duration_ms));
  const openRow = rows.find((r) => r.trace_id === open);

  function setParams(changes: Record<string, string | undefined>) {
    const next = new URLSearchParams(params);
    for (const [name, value] of Object.entries(changes)) {
      if (value === undefined || value === "" || value === ALL) next.delete(name);
      else next.set(name, value);
    }
    router.replace(`${pathname}?${next}`, { scroll: false });
  }
  const activeFilters = ["service", "through", "operation", "status", "min"].filter((k) => params.get(k));

  return (
    <div className="space-y-3 px-4 pb-8 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <FilterSelect label="Entrou por" value={filters.service} onChange={(v) => setParams({ service: v })} options={serviceNames} />
        <FilterSelect label="Passou por" value={filters.through} onChange={(v) => setParams({ through: v })} options={serviceNames} />
        <Select value={filters.status ?? ALL} onValueChange={(v) => setParams({ status: v })}>
          <SelectTrigger size="sm" className="h-7 w-36 text-xs" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos os status</SelectItem>
            <SelectItem value="error">Com erro</SelectItem>
            <SelectItem value="ok">Sem erro</SelectItem>
          </SelectContent>
        </Select>
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            setParams({
              operation: String(data.get("operation") ?? "").trim(),
              min: String(data.get("min") ?? "").trim(),
            });
          }}
        >
          <div className="relative">
            <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-faint" />
            <Input
              key={filters.operation} // um filtro vindo da busca do cabeçalho reaparece aqui
              name="operation"
              defaultValue={filters.operation}
              placeholder="Operação, ex.: /checkout"
              className="h-7 w-52 pl-7 font-mono text-xs"
            />
          </div>
          <Input
            name="min"
            type="number"
            min={0}
            defaultValue={filters.min_duration_ms}
            placeholder="Duração mín. (ms)"
            className="h-7 w-36 font-mono text-xs"
          />
          <Button type="submit" variant="secondary" size="sm">
            Filtrar
          </Button>
        </form>
        {activeFilters.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => setParams(Object.fromEntries(activeFilters.map((k) => [k, undefined])))}
          >
            <X className="size-3.5" /> Limpar filtros
          </Button>
        )}
        <span className="ml-auto flex items-center gap-2 text-xs text-faint">
          {traces.isSuccess && (
            <span className="font-mono tabular">
              {rows.length}
              {traces.hasNextPage ? "+" : ""} traces · {RANGES[range].label.toLowerCase()}
            </span>
          )}
          <Button variant="ghost" size="icon-sm" onClick={() => setNow(Date.now())} aria-label="Atualizar">
            <RefreshCw className={cn("size-3.5", traces.isFetching && "animate-spin")} />
          </Button>
        </span>
      </div>

      <div className="overflow-hidden rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-24">Horário</TableHead>
              <TableHead className="w-32">Entrou por</TableHead>
              <TableHead>Operação</TableHead>
              <TableHead className="w-56">Duração</TableHead>
              <TableHead className="w-16 text-right">Spans</TableHead>
              <TableHead className="w-20 text-right">Serviços</TableHead>
              <TableHead className="w-28">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(traces.isPending || environment === undefined) &&
              Array.from({ length: 10 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-4 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {rows.map((trace) => (
              <TraceRow
                key={trace.trace_id}
                trace={trace}
                slowest={slowest}
                selected={trace.trace_id === open}
                onOpen={() => setParams({ trace: trace.trace_id })}
              />
            ))}
          </TableBody>
        </Table>
        {traces.isSuccess && rows.length === 0 && (
          <div className="px-6 py-14 text-center text-[13px] text-muted-foreground">
            Nenhum trace com esses filtros neste período.
            <br />
            Aumente o período no cabeçalho ou tire algum filtro.
          </div>
        )}
        {traces.isError && (
          <div className="flex items-center justify-center gap-2 px-6 py-14 text-[13px] text-destructive">
            <AlertTriangle className="size-4" /> {traces.error.message}
          </div>
        )}
      </div>

      {traces.hasNextPage && (
        <div className="flex justify-center">
          <Button variant="outline" size="sm" onClick={() => traces.fetchNextPage()} disabled={traces.isFetchingNextPage}>
            {traces.isFetchingNextPage ? "Carregando…" : "Carregar mais"}
          </Button>
        </div>
      )}

      <Sheet open={open !== null} onOpenChange={(isOpen) => !isOpen && setParams({ trace: undefined })}>
        <SheetContent className="gap-0 overflow-y-auto bg-background p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-[min(1100px,92vw)]">
          <SheetTitle className="sr-only">Trace</SheetTitle>
          <SheetDescription className="sr-only">O caminho da requisição pelos serviços</SheetDescription>
          {open && <TraceView projectId={projectId} traceId={open} around={openRow?.start_time} variant="panel" />}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function TraceRow({
  trace,
  slowest,
  selected,
  onOpen,
}: {
  trace: TraceSummary;
  slowest: number;
  selected: boolean;
  onOpen: () => void;
}) {
  const failed = trace.error_count > 0;
  return (
    <TableRow
      className={cn("cursor-pointer", selected && "bg-primary/10")}
      onClick={onOpen}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
      tabIndex={0}
      aria-label={`Abrir o trace ${trace.name}`}
    >
      <TableCell className="text-muted-foreground">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="font-mono text-xs tabular">{formatClock(trace.start_time).slice(0, 8)}</span>
          </TooltipTrigger>
          <TooltipContent>{formatAgo(trace.start_time)}</TooltipContent>
        </Tooltip>
      </TableCell>
      <TableCell className="truncate font-mono text-xs text-muted-foreground">{trace.service}</TableCell>
      <TableCell className="max-w-0 truncate font-mono text-xs">{trace.name}</TableCell>
      <TableCell>
        <span className="flex items-center gap-2">
          <span className="h-1 flex-1 overflow-hidden rounded-full bg-secondary">
            <span
              className={cn("block h-full", failed ? "bg-destructive" : "bg-primary/80")}
              style={{ width: `${Math.max(2, (trace.duration_ms / slowest) * 100)}%` }}
            />
          </span>
          <span className="w-14 text-right font-mono text-xs tabular">{formatDuration(trace.duration_ms)}</span>
        </span>
      </TableCell>
      <TableCell className="text-right font-mono text-xs tabular">{trace.span_count}</TableCell>
      <TableCell className="text-right font-mono text-xs tabular">{trace.service_count}</TableCell>
      <TableCell className="font-mono text-xs">
        {failed ? (
          <span className="text-destructive">
            {trace.error_count} {trace.error_count === 1 ? "erro" : "erros"}
          </span>
        ) : (
          <span className="text-muted-foreground">ok</span>
        )}
        {trace.http_status_code && <HttpCode code={trace.http_status_code} />}
      </TableCell>
    </TableRow>
  );
}

/** 2xx discreto; 4xx em âmbar (o pedido foi recusado); 5xx em vermelho (o sistema falhou). */
export function HttpCode({ code }: { code: number }) {
  const tone = code >= 500 ? "text-destructive" : code >= 400 ? "text-warning" : "text-faint";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn("ml-2 font-mono text-xs", tone)}>{code}</span>
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
      <SelectTrigger size="sm" className={cn("h-7 w-44 text-xs", value && "border-primary/50")} aria-label={label}>
        {/* o rótulo fica no botão mesmo com um valor escolhido: "payments" sozinho não diz se
            o filtro é "entrou por" ou "passou por" */}
        <SelectValue placeholder={label}>
          <span className="text-faint">{label}:</span> <span className="font-mono">{value ?? "todos"}</span>
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{label}: todos</SelectItem>
        {options.map((option) => (
          <SelectItem key={option} value={option} className="font-mono text-xs">
            {option}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

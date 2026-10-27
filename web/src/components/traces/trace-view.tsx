"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Maximize2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { SpanInspector } from "@/components/traces/span-details";
import { Waterfall } from "@/components/traces/waterfall";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, type Span, type Trace, api } from "@/lib/api";
import { formatClock, formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Um trace: o waterfall à esquerda e o span escolhido à direita (a raiz, de início).
 * `variant="panel"` é a versão que abre ao lado da lista de traces, sem sair dela.
 */
export function TraceView({
  projectId,
  traceId,
  around,
  variant = "page",
}: {
  projectId: number;
  traceId: string;
  around?: string; // o horário aproximado deixa o banco abrir só as partições daquela hora
  variant?: "page" | "panel";
}) {
  const trace = useQuery({
    queryKey: ["trace", projectId, traceId],
    queryFn: () => api.trace(projectId, traceId, around),
    staleTime: Infinity, // um trace terminado não muda
  });
  const [chosen, setChosen] = useState<Span | null>(null);
  const page = variant === "page";

  if (trace.isError) {
    const notFound = trace.error instanceof ApiError && trace.error.status === 404;
    return (
      <>
        {page && <PageHeader title="Trace" />}
        <p className="px-4 py-16 text-center text-[13px] text-muted-foreground sm:px-6">
          {notFound ? "Trace não encontrado. Ele pode ter passado dos 3 dias de retenção." : trace.error.message}
        </p>
      </>
    );
  }
  if (!trace.data) {
    return (
      <div className="space-y-1.5 px-4 py-5 sm:px-6">
        {Array.from({ length: 10 }, (_, i) => (
          <Skeleton key={i} className="h-6 w-full" />
        ))}
      </div>
    );
  }

  const data = trace.data;
  const root = data.spans[0];
  const selected = chosen && data.spans.some((s) => s.span_id === chosen.span_id) ? chosen : root;
  const href = `/projects/${projectId}/traces/${data.trace_id}${around ? `?around=${encodeURIComponent(around)}` : ""}`;

  return (
    <>
      {page ? (
        <PageHeader title={<span className="font-mono text-xl">{root.name}</span>} description={<TraceFacts data={data} />} />
      ) : (
        <header className="flex items-start justify-between gap-3 border-b py-3 pr-12 pl-4">
          <div className="min-w-0">
            <p className="truncate font-mono text-[15px]">{root.name}</p>
            <div className="mt-1 text-xs text-muted-foreground">
              <TraceFacts data={data} />
            </div>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link href={href}>
              <Maximize2 className="size-3.5" /> Página inteira
            </Link>
          </Button>
        </header>
      )}
      <div className={cn("grid gap-4 px-4 pb-6 sm:px-6", page ? "xl:grid-cols-[minmax(0,1fr)_360px]" : "pt-4")}>
        <div className="min-w-0 space-y-2">
          <Waterfall
            spans={data.spans}
            totalMs={data.duration_ms}
            selected={selected.span_id}
            onSelect={setChosen}
          />
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-faint">
            <Legend swatch="bg-[color-mix(in_srgb,var(--primary)_72%,var(--card))]">trabalhando</Legend>
            <Legend swatch="border border-[#5a5d66] bg-[repeating-linear-gradient(135deg,#5a5d66_0_3px,transparent_3px_6px)]">
              esperando outro serviço
            </Legend>
            <Legend swatch="bg-destructive">com erro</Legend>
            <span>passe o mouse para o tempo próprio; clique para os detalhes</span>
          </p>
        </div>
        <SpanInspector span={selected} className={cn(page && "xl:sticky xl:top-16 xl:self-start")} />
      </div>
    </>
  );
}

function TraceFacts({ data }: { data: Trace }) {
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <CopyId id={data.trace_id} />
      <span className="font-mono">{formatClock(data.start_time)}</span>
      <span className="font-mono text-foreground tabular">{formatDuration(data.duration_ms)}</span>
      <span className="font-mono tabular">{data.spans.length} spans</span>
      {data.error_count > 0 ? (
        <span className="font-mono text-destructive">
          {data.error_count} {data.error_count === 1 ? "span com erro" : "spans com erro"}
        </span>
      ) : (
        <span className="text-success">sem erros</span>
      )}
      <span className="font-mono text-faint">{data.services.join(" · ")}</span>
    </span>
  );
}

function Legend({ swatch, children }: { swatch: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("inline-block h-2.5 w-4 rounded-sm", swatch)} aria-hidden />
      {children}
    </span>
  );
}

function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 font-mono hover:text-foreground"
      title="Copiar o id do trace"
      onClick={async () => {
        await navigator.clipboard.writeText(id);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {id}
      {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
    </button>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { SpanDetails } from "@/components/traces/span-details";
import { Waterfall } from "@/components/traces/waterfall";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, type Span, api } from "@/lib/api";
import { serviceColor } from "@/lib/colors";
import { formatClock, formatDuration } from "@/lib/format";

export function TraceView({ projectId, traceId }: { projectId: number; traceId: string }) {
  // ?around= vem da lista: o horário aproximado deixa o banco abrir só as partições daquela hora
  const around = useSearchParams().get("around") ?? undefined;
  const trace = useQuery({
    queryKey: ["trace", projectId, traceId],
    queryFn: () => api.trace(projectId, traceId, around),
    staleTime: Infinity, // um trace terminado não muda
  });
  const [selected, setSelected] = useState<Span | null>(null);

  const back = (
    <Button variant="ghost" size="sm" asChild>
      <Link href={`/projects/${projectId}/traces`}>
        <ArrowLeft className="size-4" /> Traces
      </Link>
    </Button>
  );

  if (trace.isError) {
    const notFound = trace.error instanceof ApiError && trace.error.status === 404;
    return (
      <>
        <PageHeader title="Trace" actions={back} />
        <p className="px-8 py-16 text-center text-sm text-muted-foreground">
          {notFound ? "Trace não encontrado. Ele pode ter passado dos 3 dias de retenção." : trace.error.message}
        </p>
      </>
    );
  }
  if (!trace.data) {
    return (
      <>
        <PageHeader title="Trace" actions={back} />
        <div className="space-y-2 px-8 py-6">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-7 w-full" />
          ))}
        </div>
      </>
    );
  }

  const data = trace.data;
  const root = data.spans[0];
  return (
    <>
      <PageHeader
        title={<span className="font-mono">{root.name}</span>}
        description={
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <CopyId id={data.trace_id} />
            <span>{formatClock(data.start_time)}</span>
          </span>
        }
        actions={back}
      />
      <div className="space-y-4 px-8 py-6">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge variant="secondary" className="font-mono tabular">
            {formatDuration(data.duration_ms)}
          </Badge>
          <Badge variant="secondary" className="tabular">
            {data.spans.length} spans
          </Badge>
          {data.error_count > 0 ? (
            <Badge variant="destructive">
              {data.error_count} {data.error_count === 1 ? "span com erro" : "spans com erro"}
            </Badge>
          ) : (
            <Badge variant="secondary" className="text-success">
              sem erros
            </Badge>
          )}
          <span className="mx-1 h-4 w-px bg-border" />
          {data.services.map((service) => (
            <span key={service} className="flex items-center gap-1.5 text-muted-foreground">
              <span className="size-2 rounded-full" style={{ background: serviceColor(service) }} />
              {service}
            </span>
          ))}
        </div>
        <Waterfall
          spans={data.spans}
          totalMs={data.duration_ms}
          selected={selected?.span_id ?? null}
          onSelect={setSelected}
        />
        <p className="text-xs text-muted-foreground">
          Barra cheia: o serviço trabalhando. Barra listrada: esperando outro serviço responder. Passe o mouse para ver o
          tempo próprio; clique para os detalhes.
        </p>
      </div>
      <SpanDetails span={selected} onClose={() => setSelected(null)} />
    </>
  );
}

function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 font-mono hover:text-foreground"
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

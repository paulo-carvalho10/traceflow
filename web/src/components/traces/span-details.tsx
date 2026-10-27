"use client";

import { CircleAlert } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Span } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Tudo o que se sabe de um span, numa coluna ao lado do waterfall (e não numa janela por cima
 * dele): dá para clicar de span em span e comparar, sem perder a árvore de vista.
 */
export function SpanInspector({ span, className }: { span: Span; className?: string }) {
  const failed = span.status === "error";
  return (
    <aside className={cn("min-w-0 rounded-lg border bg-card", className)} aria-label="Detalhes do span">
      <header className="border-b px-3 py-2.5">
        <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
          {span.service}
          <span className="text-faint">· {span.kind}</span>
          {failed && (
            <span className="ml-auto inline-flex items-center gap-1 text-destructive">
              <CircleAlert className="size-3.5" /> erro
            </span>
          )}
        </div>
        <p className="mt-1 font-mono text-[13px] break-all">
          {span.peer_address ? `${span.name} → ${span.peer_address}` : span.name}
        </p>
      </header>
      <dl className="grid grid-cols-3 divide-x border-b">
        <Stat label="Duração" value={formatDuration(span.duration_ms)} />
        <Stat label="Tempo próprio" value={formatDuration(span.self_time_ms)} />
        <Stat label="Começou em" value={`+${formatDuration(span.offset_ms)}`} />
      </dl>
      <Tabs defaultValue="resumo" className="px-3 py-2.5">
        <TabsList className="h-7">
          <TabsTrigger value="resumo" className="text-xs">
            Resumo
          </TabsTrigger>
          <TabsTrigger value="atributos" className="text-xs">
            Atributos
          </TabsTrigger>
          <TabsTrigger value="eventos" className="text-xs">
            Eventos ({span.events.length})
          </TabsTrigger>
        </TabsList>
        <TabsContent value="resumo" className="mt-2">
          <Fields
            rows={[
              ["status", failed ? <span className="text-destructive">erro</span> : span.status === "ok" ? "ok" : "sem erro"],
              ["mensagem", span.status_message],
              ["http", [span.http_method, span.http_route, span.http_status_code].filter(Boolean).join(" ")],
              ["destino", span.peer_address],
              ["span_id", span.span_id],
              ["parent_id", span.parent_span_id ?? "nenhum (é a raiz)"],
            ]}
          />
        </TabsContent>
        <TabsContent value="atributos" className="mt-2 space-y-4">
          <KeyValues title="Do span" values={span.attributes} />
          <KeyValues title="Do serviço (recurso)" values={span.resource} />
        </TabsContent>
        <TabsContent value="eventos" className="mt-2 space-y-2">
          {span.events.length === 0 && <p className="text-xs text-muted-foreground">Nenhum evento.</p>}
          {span.events.map((event, i) => (
            <div key={i} className="rounded-md border p-2">
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="font-mono">{String(event.name)}</span>
                <span className="font-mono text-faint">+{formatDuration(Number(event.offset_ms))}</span>
              </div>
              <KeyValues values={(event.attributes ?? {}) as Record<string, unknown>} />
            </div>
          ))}
        </TabsContent>
      </Tabs>
    </aside>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-3 py-2">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-mono text-[13px] tabular">{value}</dd>
    </div>
  );
}

function Fields({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="divide-y divide-border/50">
      {rows
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([label, value]) => (
          <div key={label} className="grid grid-cols-[96px_1fr] gap-2 py-1.5 text-xs">
            <dt className="font-mono text-faint">{label}</dt>
            <dd className="font-mono break-all">{value}</dd>
          </div>
        ))}
    </dl>
  );
}

function KeyValues({ title, values }: { title?: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div>
      {title && <h3 className="mb-1 text-[11px] text-muted-foreground">{title}</h3>}
      {entries.length === 0 ? (
        <p className="text-xs text-faint">Nenhum.</p>
      ) : (
        <Fields rows={entries.map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)])} />
      )}
    </div>
  );
}

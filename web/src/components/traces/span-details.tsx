"use client";

import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Span } from "@/lib/api";
import { serviceColor } from "@/lib/colors";
import { formatDuration } from "@/lib/format";

/** O painel lateral com tudo o que se sabe de um span. */
export function SpanDetails({ span, onClose }: { span: Span | null; onClose: () => void }) {
  return (
    <Sheet open={span !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        {span && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                <span className="size-2.5 rounded-full" style={{ background: serviceColor(span.service) }} />
                {span.service}
              </SheetTitle>
              <SheetDescription className="font-mono">
                {span.peer_address ? `${span.name} → ${span.peer_address}` : span.name}
              </SheetDescription>
            </SheetHeader>
            <div className="px-4 pb-6">
              <div className="mb-5 grid grid-cols-3 gap-3">
                <Stat label="Duração" value={formatDuration(span.duration_ms)} />
                <Stat label="Tempo próprio" value={formatDuration(span.self_time_ms)} />
                <Stat label="Começou em" value={`+${formatDuration(span.offset_ms)}`} />
              </div>
              <Tabs defaultValue="resumo">
                <TabsList>
                  <TabsTrigger value="resumo">Resumo</TabsTrigger>
                  <TabsTrigger value="atributos">Atributos</TabsTrigger>
                  <TabsTrigger value="eventos">Eventos ({span.events.length})</TabsTrigger>
                </TabsList>
                <TabsContent value="resumo" className="mt-4">
                  <Fields
                    rows={[
                      ["Tipo", span.kind],
                      ["Status", <StatusBadge key="s" status={span.status} />],
                      ["Mensagem", span.status_message],
                      ["HTTP", [span.http_method, span.http_route, span.http_status_code].filter(Boolean).join(" ")],
                      ["Destino", span.peer_address],
                      ["Span", span.span_id],
                      ["Pai", span.parent_span_id ?? "nenhum (é a raiz)"],
                    ]}
                  />
                </TabsContent>
                <TabsContent value="atributos" className="mt-4 space-y-6">
                  <KeyValues title="Do span" values={span.attributes} />
                  <KeyValues title="Do serviço (recurso)" values={span.resource} />
                </TabsContent>
                <TabsContent value="eventos" className="mt-4 space-y-3">
                  {span.events.length === 0 && <p className="text-sm text-muted-foreground">Nenhum evento.</p>}
                  {span.events.map((event, i) => (
                    <div key={i} className="rounded-lg border p-3">
                      <div className="mb-2 flex items-center justify-between text-sm">
                        <span className="font-medium">{String(event.name)}</span>
                        <span className="font-mono text-xs text-muted-foreground">
                          +{formatDuration(Number(event.offset_ms))}
                        </span>
                      </div>
                      <KeyValues values={(event.attributes ?? {}) as Record<string, unknown>} />
                    </div>
                  ))}
                </TabsContent>
              </Tabs>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-muted/40 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-sm tabular">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "error") return <Badge variant="destructive">erro</Badge>;
  return <Badge variant="secondary">{status === "ok" ? "ok" : "sem erro"}</Badge>;
}

function Fields({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="divide-y divide-border/60 text-sm">
      {rows
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([label, value]) => (
          <div key={label} className="grid grid-cols-[110px_1fr] gap-3 py-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-mono text-[13px] break-all">{value}</dd>
          </div>
        ))}
    </dl>
  );
}

function KeyValues({ title, values }: { title?: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div>
      {title && <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>}
      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nenhum.</p>
      ) : (
        <Fields rows={entries.map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)])} />
      )}
    </div>
  );
}

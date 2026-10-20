"use client";

import { ChevronDown, ChevronRight, CircleAlert, Unlink } from "lucide-react";
import { useMemo, useState } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Span } from "@/lib/api";
import { serviceColor } from "@/lib/colors";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";
import { barPosition, ticks } from "@/lib/waterfall";

const INDENT_PX = 14;

/**
 * O waterfall: uma linha por span, na ordem da árvore (a API já manda assim, com a
 * profundidade de cada um). À esquerda, quem fez o quê; à direita, quando e por quanto tempo.
 */
export function Waterfall({
  spans,
  totalMs,
  selected,
  onSelect,
}: {
  spans: Span[];
  totalMs: number;
  selected: string | null;
  onSelect: (span: Span) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const visible = useMemo(() => visibleSpans(spans, collapsed), [spans, collapsed]);
  const marks = ticks(totalMs);

  function toggle(spanId: string) {
    setCollapsed((current) => {
      const next = new Set(current); // estado é imutável no React: cria um novo conjunto
      if (next.has(spanId)) next.delete(spanId);
      else next.add(spanId);
      return next;
    });
  }

  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="grid grid-cols-[minmax(260px,32%)_1fr] border-b text-xs text-muted-foreground">
        <div className="px-4 py-2">Serviço e operação</div>
        <div className="relative h-8">
          {marks.map((ms) => (
            <span
              key={ms}
              className="absolute top-2 -translate-x-1/2 font-mono tabular first:translate-x-0"
              style={{ left: `${(ms / totalMs) * 100}%` }}
            >
              {formatDuration(ms)}
            </span>
          ))}
        </div>
      </div>

      <div role="list">
        {visible.map((span) => {
          const bar = barPosition(span.offset_ms, span.duration_ms, totalMs);
          const color = serviceColor(span.service);
          const isClient = span.kind === "client" || span.kind === "producer";
          const failed = span.status === "error";
          return (
            <div
              key={span.span_id}
              role="listitem"
              onClick={() => onSelect(span)}
              className={cn(
                "grid cursor-pointer grid-cols-[minmax(260px,32%)_1fr] border-b border-border/50 text-sm last:border-b-0 hover:bg-accent/40",
                selected === span.span_id && "bg-accent/70",
              )}
            >
              <div
                className="flex min-w-0 items-center gap-1.5 py-1.5 pr-3"
                style={{ paddingLeft: 12 + span.depth * INDENT_PX }}
              >
                {span.children > 0 ? (
                  <button
                    type="button"
                    aria-label={collapsed.has(span.span_id) ? "Expandir" : "Recolher"}
                    className="rounded text-muted-foreground hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation(); // recolher não deve também abrir os detalhes
                      toggle(span.span_id);
                    }}
                  >
                    {collapsed.has(span.span_id) ? (
                      <ChevronRight className="size-3.5" />
                    ) : (
                      <ChevronDown className="size-3.5" />
                    )}
                  </button>
                ) : (
                  <span className="w-3.5" />
                )}
                <span className="size-2 shrink-0 rounded-full" style={{ background: color }} />
                <span className="shrink-0 font-medium" style={{ color }}>
                  {span.service}
                </span>
                <span className="truncate font-mono text-[12.5px] text-foreground/90">
                  {isClient && span.peer_address ? `${span.name} → ${span.peer_address}` : span.name}
                </span>
                {failed && <CircleAlert className="size-3.5 shrink-0 text-destructive" />}
                {span.orphan && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Unlink className="size-3.5 shrink-0 text-warning" />
                    </TooltipTrigger>
                    <TooltipContent>O span pai não está neste trace (ainda não chegou ou se perdeu)</TooltipContent>
                  </Tooltip>
                )}
              </div>

              <div className="relative">
                {marks.map((ms) => (
                  <span
                    key={ms}
                    className="absolute inset-y-0 w-px bg-border/40"
                    style={{ left: `${(ms / totalMs) * 100}%` }}
                  />
                ))}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      className={cn(
                        "absolute top-1/2 h-3.5 -translate-y-1/2 rounded-[3px]",
                        failed && "ring-2 ring-destructive",
                      )}
                      style={{
                        left: `${bar.left}%`,
                        width: `${bar.width}%`,
                        // chamada a outro serviço: barra listrada (esperando); cheia: trabalhando
                        background: isClient
                          ? `repeating-linear-gradient(135deg, ${color} 0 4px, color-mix(in srgb, ${color} 35%, transparent) 4px 8px)`
                          : color,
                      }}
                    />
                  </TooltipTrigger>
                  <TooltipContent className="font-mono text-xs">
                    começou em +{formatDuration(span.offset_ms)} · durou {formatDuration(span.duration_ms)}
                    <br />
                    tempo próprio {formatDuration(span.self_time_ms)}
                  </TooltipContent>
                </Tooltip>
                {bar.left + bar.width > 88 && bar.width < 12 ? (
                  // barra estreita no fim da linha: a duração vai antes dela, à esquerda
                  <span
                    className="pointer-events-none absolute top-1/2 -translate-y-1/2 pr-1.5 text-right font-mono text-[11px] text-muted-foreground tabular"
                    style={{ right: `${100 - bar.left}%` }}
                  >
                    {formatDuration(span.duration_ms)}
                  </span>
                ) : bar.left + bar.width > 88 ? (
                  // barra larga que chega ao fim da linha: a duração vai dentro dela, no fim
                  <span
                    className="pointer-events-none absolute top-1/2 -translate-y-1/2 pr-1.5 text-right font-mono text-[11px] font-semibold text-background tabular"
                    style={{ right: `${100 - bar.left - bar.width}%` }}
                  >
                    {formatDuration(span.duration_ms)}
                  </span>
                ) : (
                  <span
                    className="pointer-events-none absolute top-1/2 -translate-y-1/2 pl-1.5 font-mono text-[11px] text-muted-foreground tabular"
                    style={{ left: `${bar.left + bar.width}%` }}
                  >
                    {formatDuration(span.duration_ms)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Esconde os descendentes dos spans recolhidos (os que vêm logo depois, mais fundos). */
export function visibleSpans(spans: Span[], collapsed: Set<string>): Span[] {
  const result: Span[] = [];
  let hideDeeperThan: number | null = null;
  for (const span of spans) {
    if (hideDeeperThan !== null && span.depth > hideDeeperThan) continue;
    hideDeeperThan = collapsed.has(span.span_id) ? span.depth : null;
    result.push(span);
  }
  return result;
}

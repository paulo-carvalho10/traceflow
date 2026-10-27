"use client";

import { ChevronDown, ChevronRight, CircleAlert, Unlink } from "lucide-react";
import { useMemo, useState } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Span } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";
import { barPosition, ticks } from "@/lib/waterfall";

const INDENT_PX = 14;

// As barras: o serviço trabalhando (cheia, no tom do destaque), esperando outro serviço
// (listrada, neutra) e com erro (vermelha). Serviço não tem cor própria: o nome está na linha.
const WORK = "color-mix(in srgb, var(--primary) 72%, var(--card))";
const WAIT = "repeating-linear-gradient(135deg, #5a5d66 0 3px, transparent 3px 6px)";
const FAIL = "var(--destructive)";

/**
 * O waterfall: uma linha por span, na ordem da árvore (a API já manda assim, com a
 * profundidade de cada um). À esquerda, quem fez o quê, com as guias da árvore; à direita,
 * quando e por quanto tempo.
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
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="grid grid-cols-[minmax(240px,34%)_1fr] border-b text-[11px] text-faint">
        <div className="px-3 py-1.5">Serviço e operação</div>
        <div className="relative h-7">
          {marks.map((ms) => (
            <span
              key={ms}
              className={cn(
                "absolute top-1.5 font-mono whitespace-nowrap tabular",
                // perto da borda direita, o rótulo fica à esquerda da marca para não quebrar a linha
                ms === 0 ? "" : ms / totalMs > 0.9 ? "-translate-x-full pr-1" : "-translate-x-1/2",
              )}
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
          const isClient = span.kind === "client" || span.kind === "producer";
          const failed = span.status === "error";
          return (
            <div
              key={span.span_id}
              role="listitem"
              onClick={() => onSelect(span)}
              aria-current={selected === span.span_id ? "true" : undefined}
              className={cn(
                "grid h-7 cursor-pointer grid-cols-[minmax(240px,34%)_1fr] border-b border-border/40 text-xs transition-colors duration-75 last:border-b-0 hover:bg-accent/50",
                selected === span.span_id && "bg-primary/10 hover:bg-primary/15",
              )}
            >
              <div className="flex min-w-0 items-stretch pr-3 pl-2">
                {Array.from({ length: span.depth }, (_, d) => (
                  // as guias da árvore: uma linha vertical por nível acima deste span
                  <span key={d} className="shrink-0 border-l border-border/70" style={{ width: INDENT_PX, marginLeft: d === 0 ? 6 : 0 }} />
                ))}
                <span className="flex min-w-0 flex-1 items-center gap-1.5">
                {span.children > 0 ? (
                  <button
                    type="button"
                    aria-label={collapsed.has(span.span_id) ? "Expandir" : "Recolher"}
                    className="rounded text-faint hover:text-foreground"
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
                <span className={cn("shrink-0 font-mono", failed ? "text-destructive" : "text-muted-foreground")}>
                  {span.service}
                </span>
                <span className="truncate font-mono text-foreground">
                  {isClient && span.peer_address ? `${span.name} → ${span.peer_address}` : span.name}
                </span>
                {failed && <CircleAlert className="size-3.5 shrink-0 text-destructive" aria-label="com erro" />}
                {span.orphan && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Unlink className="size-3.5 shrink-0 text-warning" />
                    </TooltipTrigger>
                    <TooltipContent>O span pai não está neste trace (ainda não chegou ou se perdeu)</TooltipContent>
                  </Tooltip>
                )}
                </span>
              </div>

              <div className="relative">
                {marks.map((ms) => (
                  <span
                    key={ms}
                    className="absolute inset-y-0 w-px bg-border/30"
                    style={{ left: `${(ms / totalMs) * 100}%` }}
                  />
                ))}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div
                      className={cn(
                        "absolute top-1/2 h-3 -translate-y-1/2 rounded-sm",
                        isClient && "border border-[#5a5d66]",
                        failed && isClient && "border-destructive",
                      )}
                      style={{
                        left: `${bar.left}%`,
                        width: `${bar.width}%`,
                        // chamada a outro serviço: barra listrada (esperando); cheia: trabalhando
                        background: failed && !isClient ? FAIL : isClient ? WAIT : WORK,
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
                    className={cn(
                      "pointer-events-none absolute top-1/2 -translate-y-1/2 pr-1.5 text-right font-mono text-[11px] font-medium tabular",
                      isClient ? "text-foreground" : "text-background", // nas listras, texto claro
                    )}
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

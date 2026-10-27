"use client";

import { useQuery } from "@tanstack/react-query";
import { Boxes, Search, Waypoints } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useWorkspace } from "@/components/workspace";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Suggestion = { kind: "trace" | "service" | "route"; label: string; detail: string; href: string };

const TRACE_ID = /^[0-9a-f]{32}$/i;

/**
 * A busca do cabeçalho. Um id de trace abre o trace; o nome de um serviço abre o serviço;
 * o resto vira uma busca de traces pela rota ("/checkout"). A tecla "/" põe o cursor aqui.
 */
export function GlobalSearch() {
  const router = useRouter();
  const { projectId, environment, scoped } = useWorkspace();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const catalog = useQuery({
    queryKey: ["services", projectId, environment],
    queryFn: () => api.services(projectId, environment),
    enabled: environment !== undefined,
  });

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const typing = event.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        input.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const query = text.trim();
  const base = `/projects/${projectId}`;
  const suggestions: Suggestion[] = [];
  if (TRACE_ID.test(query)) {
    suggestions.push({ kind: "trace", label: query.toLowerCase(), detail: "abrir o trace", href: `${base}/traces/${query.toLowerCase()}` });
  } else if (query) {
    for (const service of catalog.data ?? []) {
      if (service.name.toLowerCase().includes(query.toLowerCase())) {
        suggestions.push({
          kind: "service",
          label: service.name,
          detail: "serviço",
          href: scoped(`${base}/services/${encodeURIComponent(service.name)}`),
        });
      }
    }
    suggestions.push({
      kind: "route",
      label: query,
      detail: "buscar traces pela operação",
      href: scoped(`${base}/traces?operation=${encodeURIComponent(query)}`),
    });
  }

  function go(suggestion: Suggestion | undefined) {
    if (!suggestion) return;
    router.push(suggestion.href);
    setText("");
    setOpen(false);
    input.current?.blur();
  }

  return (
    <div className="relative hidden md:block">
      <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-faint" />
      <input
        ref={input}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)} // deixa o clique numa sugestão chegar antes
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((i) => Math.min(i + 1, suggestions.length - 1));
          else if (e.key === "ArrowUp") setActive((i) => Math.max(i - 1, 0));
          else if (e.key === "Enter") go(suggestions[active]);
          else if (e.key === "Escape") input.current?.blur();
          else return;
          e.preventDefault();
        }}
        placeholder="Trace id, serviço ou rota"
        aria-label="Buscar trace, serviço ou rota"
        className="h-7 w-56 rounded-md border border-input bg-card pr-7 pl-7 text-xs placeholder:text-faint focus:w-72 focus:border-ring focus:outline-none lg:w-64 transition-[width] duration-150"
      />
      <kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 font-mono text-[10px] text-faint">/</kbd>
      {open && suggestions.length > 0 && (
        <ul
          role="listbox"
          className="absolute top-8 right-0 z-50 w-80 overflow-hidden rounded-md border bg-popover py-1 shadow-lg"
        >
          {suggestions.map((s, i) => {
            const Icon = s.kind === "service" ? Boxes : s.kind === "trace" ? Waypoints : Search;
            return (
              <li key={`${s.kind}:${s.label}`} role="option" aria-selected={i === active}>
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => go(s)}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs",
                    i === active && "bg-accent",
                  )}
                >
                  <Icon className="size-3.5 shrink-0 text-faint" />
                  <span className={cn("min-w-0 flex-1 truncate", s.kind !== "route" && "font-mono")}>{s.label}</span>
                  <span className="shrink-0 text-faint">{s.detail}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleCheck, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { SeverityBadge } from "@/components/incidents/badges";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useWorkspace } from "@/components/workspace";
import { useNow } from "@/hooks/use-now";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { formatElapsed } from "@/lib/incidents";
import type { Severity } from "@/lib/live";
import { cn } from "@/lib/utils";

type StatusFilter = "todos" | "open" | "resolved";

/**
 * Os incidentes do ambiente, numa tabela só: os abertos primeiro. Um incidente abre sozinho
 * quando um serviço sai de saudável por 3 s seguidos, e resolve depois de 30 s com tudo saudável.
 */
export function IncidentsView() {
  const router = useRouter();
  const now = useNow();
  const { projectId, environment } = useWorkspace();
  const [status, setStatus] = useState<StatusFilter>("todos");
  const [severity, setSeverity] = useState<Severity | "todas">("todas");
  const incidents = useQuery({
    queryKey: ["incidents", projectId, "all", environment],
    queryFn: () => api.incidents(projectId, { environment }),
    enabled: environment !== undefined,
    refetchInterval: 5_000,
  });

  const all = incidents.data ?? [];
  const peak = (i: (typeof all)[number]) => (i.status === "open" ? i.severity : i.peak_severity) as Severity;
  const rows = all
    .filter((i) => status === "todos" || i.status === status)
    .filter((i) => severity === "todas" || peak(i) === severity)
    .sort((a, b) => (a.status === b.status ? b.opened_at.localeCompare(a.opened_at) : a.status === "open" ? -1 : 1));
  const openCount = all.filter((i) => i.status === "open").length;

  return (
    <div className="space-y-3 px-4 pb-8 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          label="Estado"
          value={status}
          onChange={setStatus}
          options={[
            ["todos", `Todos ${all.length}`],
            ["open", `Abertos ${openCount}`],
            ["resolved", `Resolvidos ${all.length - openCount}`],
          ]}
        />
        <Segmented
          label="Severidade"
          value={severity}
          onChange={setSeverity}
          options={[
            ["todas", "Todas"],
            ["SEV1", "SEV1"],
            ["SEV2", "SEV2"],
            ["SEV3", "SEV3"],
          ]}
        />
        <Button variant="outline" size="sm" className="ml-auto" asChild>
          <Link href={`/projects/${projectId}/settings/rules`}>
            <SlidersHorizontal className="size-3.5" /> Regras de detecção
          </Link>
        </Button>
      </div>

      {openCount === 0 && incidents.isSuccess && (
        <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <CircleCheck className="size-4 text-success" /> Nenhum incidente aberto neste ambiente.
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-32">Severidade</TableHead>
              <TableHead className="w-28">Estado</TableHead>
              <TableHead>Incidente</TableHead>
              <TableHead>Causa provável</TableHead>
              <TableHead className="w-24">Ambiente</TableHead>
              <TableHead className="w-40">Início</TableHead>
              <TableHead className="w-24 text-right">Duração</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {incidents.isPending &&
              Array.from({ length: 5 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-4 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {rows.map((i) => {
              const href = `/projects/${projectId}/incidents/${i.id}`;
              const open = i.status === "open";
              return (
                <TableRow
                  key={i.id}
                  className={cn("cursor-pointer", open && "bg-destructive/[0.04]")}
                  tabIndex={0}
                  onClick={() => router.push(href)}
                  onKeyDown={(e) => e.key === "Enter" && router.push(href)}
                >
                  <TableCell>
                    <SeverityBadge severity={peak(i)} />
                  </TableCell>
                  <TableCell className="text-xs">
                    {open ? (
                      <span className="inline-flex items-center gap-1.5 text-destructive">
                        <span className="size-1.5 animate-pulse rounded-full bg-destructive" /> aberto
                      </span>
                    ) : (
                      <span className="text-muted-foreground">resolvido</span>
                    )}
                  </TableCell>
                  <TableCell className="min-w-56">
                    <Link href={href} className="hover:text-primary" onClick={(e) => e.stopPropagation()}>
                      {i.title}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{i.causes.join(", ") || "–"}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{i.environment}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground tabular">{formatDateTime(i.opened_at)}</TableCell>
                  <TableCell className={cn("text-right font-mono text-xs tabular", open && "text-destructive")}>
                    {formatElapsed(i.opened_at, i.resolved_at ?? now)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        {incidents.isSuccess && rows.length === 0 && (
          <p className="px-6 py-12 text-center text-[13px] text-muted-foreground">
            {all.length === 0 ? "Nenhum incidente neste ambiente ainda." : "Nenhum incidente com esse filtro."}
          </p>
        )}
      </div>
    </div>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div className="inline-flex h-7 overflow-hidden rounded-md border text-xs" role="group" aria-label={label}>
      {options.map(([key, text]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          aria-pressed={value === key}
          className={cn(
            "border-r px-2.5 transition-colors duration-100 last:border-r-0",
            value === key ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

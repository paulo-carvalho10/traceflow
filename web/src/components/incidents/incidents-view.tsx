"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleCheck, SlidersHorizontal } from "lucide-react";
import Link from "next/link";

import { SeverityBadge } from "@/components/incidents/badges";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useNow } from "@/hooks/use-now";
import { type IncidentSummary, api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { formatElapsed } from "@/lib/incidents";
import type { Severity } from "@/lib/live";

/** Os incidentes do projeto: os abertos agora, em destaque, e o histórico. */
export function IncidentsView({ projectId }: { projectId: number }) {
  const now = useNow();
  // a mesma chave do vigia do menu: os dois compartilham a consulta
  const open = useQuery({
    queryKey: ["incidents", projectId, "open"],
    queryFn: () => api.incidents(projectId, { status: "open" }),
    refetchInterval: 5_000,
  });
  const history = useQuery({
    queryKey: ["incidents", projectId, "resolved"],
    queryFn: () => api.incidents(projectId, { status: "resolved" }),
    refetchInterval: 15_000,
  });

  return (
    <div className="space-y-6 px-4 py-5 sm:px-8 sm:py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Um incidente abre sozinho quando um serviço sai de saudável por 3 segundos seguidos, e resolve depois de 30
          segundos com tudo saudável. A causa, o impacto e a severidade são recalculados a cada segundo.
        </p>
        <Button variant="outline" size="sm" asChild>
          <Link href={`/projects/${projectId}/incidents/rules`}>
            <SlidersHorizontal className="size-4" /> Regras de detecção
          </Link>
        </Button>
      </div>

      <section aria-labelledby="abertos" className="space-y-3">
        <h2 id="abertos" className="text-sm font-medium">
          Abertos agora
        </h2>
        {open.isPending ? (
          <Skeleton className="h-20 rounded-xl" />
        ) : open.data?.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {open.data.map((incident) => (
              <OpenCard key={incident.id} incident={incident} projectId={projectId} now={now} />
            ))}
          </div>
        ) : (
          <p className="flex items-center gap-2 rounded-xl border border-dashed bg-card px-4 py-5 text-sm text-muted-foreground">
            <CircleCheck className="size-4 text-success" /> Nenhum incidente aberto: todos os serviços estão saudáveis.
          </p>
        )}
      </section>

      <section aria-labelledby="historico" className="space-y-3">
        <h2 id="historico" className="text-sm font-medium">
          Histórico
        </h2>
        {history.data?.length ? (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Severidade</TableHead>
                  <TableHead>Incidente</TableHead>
                  <TableHead>Causa provável</TableHead>
                  <TableHead>Ambiente</TableHead>
                  <TableHead>Início</TableHead>
                  <TableHead className="text-right">Duração</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.data.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell>
                      <SeverityBadge severity={i.peak_severity as Severity} />
                    </TableCell>
                    <TableCell className="min-w-48">
                      <Link href={`/projects/${projectId}/incidents/${i.id}`} className="font-medium hover:text-primary">
                        {i.title}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{i.causes.join(", ") || "–"}</TableCell>
                    <TableCell className="text-muted-foreground">{i.environment}</TableCell>
                    <TableCell className="font-mono text-xs whitespace-nowrap tabular">{formatDateTime(i.opened_at)}</TableCell>
                    <TableCell className="text-right font-mono text-xs whitespace-nowrap tabular">
                      {i.resolved_at ? formatElapsed(i.opened_at, i.resolved_at) : "–"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{history.isPending ? "Carregando…" : "Nenhum incidente resolvido ainda."}</p>
        )}
      </section>
    </div>
  );
}

function OpenCard({ incident, projectId, now }: { incident: IncidentSummary; projectId: number; now: number }) {
  return (
    <Link
      href={`/projects/${projectId}/incidents/${incident.id}`}
      className="flex flex-col gap-2 rounded-xl border border-destructive/30 bg-card p-4 transition-colors hover:border-primary"
    >
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={incident.severity as Severity} />
        <span className="text-xs text-muted-foreground">{incident.environment}</span>
        <span className="ml-auto font-mono text-xs text-muted-foreground tabular">
          há {formatElapsed(incident.opened_at, now)}
        </span>
      </div>
      <span className="font-medium">{incident.title}</span>
      {incident.causes.length > 0 && (
        <span className="text-xs text-muted-foreground">Causa provável: {incident.causes.join(", ")}</span>
      )}
    </Link>
  );
}

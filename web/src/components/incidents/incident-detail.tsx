"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CircleCheck, Clock, Crosshair, Globe, Network, Radio, Users, Waypoints } from "lucide-react";
import Link from "next/link";

import { SeverityBadge, StateLabel } from "@/components/incidents/badges";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useLive } from "@/hooks/use-live";
import { useNow } from "@/hooks/use-now";
import { ApiError, type EndpointComparison, type IncidentDetail, type Period, api } from "@/lib/api";
import { formatDuration, formatPercent, formatRate } from "@/lib/format";
import { STATE, formatElapsed, recovery, tracesPeriodFor } from "@/lib/incidents";
import type { HealthState, IncidentCause, LiveIncident, Severity } from "@/lib/live";
import { cn } from "@/lib/utils";

/**
 * Um incidente: o que quebrou (causa provável), quem sente (as rotas de entrada), as provas
 * (onde os erros nasceram nos traces), a história (linha do tempo) e o antes / depois.
 * Aberto, os números vêm do retrato ao vivo, segundo a segundo.
 */
export function IncidentDetailView({ projectId, incidentId }: { projectId: number; incidentId: string }) {
  const now = useNow();
  const detail = useQuery({
    queryKey: ["incident", projectId, incidentId],
    queryFn: () => api.incident(projectId, incidentId),
    // aberto: a linha do tempo cresce; resolvido: só falta o "depois" completar
    refetchInterval: (q) => (q.state.data?.status === "open" ? 3_000 : q.state.data?.comparison.some((c) => !c.after_complete) ? 30_000 : false),
  });
  const data = detail.data;
  const { snapshot } = useLive(projectId, data?.status === "open" ? data.environment : undefined);
  const live = snapshot?.incident?.id === incidentId ? snapshot.incident : null;
  const healing = live ? recovery(live, now) : null;

  if (detail.error instanceof ApiError && detail.error.status === 404) {
    return <p className="px-4 py-16 text-center text-sm text-muted-foreground sm:px-8">Incidente não encontrado.</p>;
  }
  if (!data) {
    return (
      <div className="space-y-4 px-4 py-5 sm:px-8 sm:py-6">
        <Skeleton className="h-16 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  const severity = (live?.severity ?? data.severity) as Severity;
  const causes: IncidentCause[] = live?.causes ?? (data.causes_detail as IncidentCause[]);
  const affected = live?.affected ?? (data.affected as LiveIncident["affected"]);
  const atRisk = live?.at_risk ?? data.at_risk;
  const endpoints = live?.endpoints ?? (data.endpoints as LiveIncident["endpoints"]);
  const period = tracesPeriodFor(data.opened_at, now);
  const env = `environment=${encodeURIComponent(data.environment)}`;

  return (
    <div className="space-y-6 px-4 py-5 sm:px-8 sm:py-6">
      <h2 className="text-xl font-semibold tracking-tight">{live?.title ?? data.title}</h2>
      <header className="-mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* aberto: a severidade de agora; resolvido: o pico, que diz o quão grave ele foi */}
        <SeverityBadge severity={data.status === "open" ? severity : (data.peak_severity as Severity)} className="text-sm" />
        {data.status === "open" && data.peak_severity !== severity && (
          <span className="text-xs text-muted-foreground">chegou a {data.peak_severity}</span>
        )}
        {data.status === "open" && healing ? (
          <span className="flex items-center gap-1.5 text-sm font-medium text-success" role="status">
            <CircleCheck className="size-4" /> Em recuperação: tudo saudável há {healing.healthyFor} s, resolve em{" "}
            {healing.resolvesIn} s se continuar assim
          </span>
        ) : data.status === "open" ? (
          <span className="flex items-center gap-1.5 text-sm font-medium text-destructive">
            <Radio className="size-4 animate-pulse" /> Aberto há {formatElapsed(data.opened_at, now)}
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-sm text-success">
            <CircleCheck className="size-4" /> Resolvido · durou {formatElapsed(data.opened_at, data.resolved_at!)}
          </span>
        )}
        <span className="text-sm text-muted-foreground">ambiente {data.environment}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href={`/projects/${projectId}/map?${env}`}>
              <Network className="size-4" /> Ver no mapa
            </Link>
          </Button>
        </div>
      </header>

      {healing && (
        <div className="space-y-1.5 rounded-xl border border-success/40 bg-success/5 px-4 py-3 text-sm">
          <p>
            A falha acabou e todos os serviços estão saudáveis. O incidente espera {live?.resolve_after_s} s assim
            antes de resolver: se a falha voltar nesse meio-tempo, ela continua sendo este incidente, e não um novo.
          </p>
          <div className="h-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-success transition-[width] duration-1000 ease-linear"
              style={{ width: `${healing.progress * 100}%` }}
            />
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Causa provável" icon={Crosshair} className="lg:col-span-2">
          {causes.length ? (
            <ul className="space-y-3">
              {causes.map((c) => (
                <li key={c.node} className="flex flex-wrap items-start gap-x-3 gap-y-1">
                  <span className="flex items-center gap-1.5 text-base font-semibold">
                    {c.virtual && <Globe className="size-4 text-muted-foreground" />}
                    {c.node}
                  </span>
                  {healing ? (
                    <span className="mt-1 text-xs text-muted-foreground">
                      <StateLabel state="healthy" /> agora (estava {STATE[c.state].label})
                    </span>
                  ) : (
                    <StateLabel state={c.state} className="mt-1" />
                  )}
                  <span className="basis-full text-sm text-muted-foreground">
                    {c.reason}.{" "}
                    {c.own
                      ? "Doente além do que as dependências dele explicam: tem problema próprio."
                      : c.virtual
                        ? "Sistema externo (não manda spans): medido pelas chamadas que chegam nele, e nada abaixo dele está doente."
                        : healing
                          ? "Estava doente sem depender de nenhum outro serviço doente: foi por onde a falha começou."
                          : "Está doente e não depende de nenhum outro serviço doente: é por onde a falha começou."}
                  </span>
                  <span className="flex basis-full flex-wrap gap-3 text-xs">
                    {!c.virtual && (
                      <>
                        <Link
                          className="text-primary hover:underline"
                          href={`/projects/${projectId}/traces?${env}&through=${encodeURIComponent(c.node)}&status=error&period=${period}`}
                        >
                          Traces com erro que passaram por {c.node} →
                        </Link>
                        <Link className="text-primary hover:underline" href={`/projects/${projectId}/services/${encodeURIComponent(c.node)}?${env}`}>
                          Abrir o serviço →
                        </Link>
                      </>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Ainda indefinida.</p>
          )}
          <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
            A causa é provável, não provada: são os serviços doentes que não dependem de nenhum outro doente (a falha
            sobe pelas chamadas). Uma correlação explicada, e por isso cada causa vem com o motivo.
          </p>
        </Card>

        <Card title="Quem sente" icon={Users}>
          {endpoints.length ? (
            <ul className="space-y-2">
              {endpoints.map((e) => (
                <li key={`${e.service} ${e.route}`} className="text-sm">
                  <span className="font-mono text-xs">{e.route}</span>
                  <span className="block text-xs text-muted-foreground tabular">
                    erro {formatPercent(e.error_rate)} · p95 {e.p95_ms === null ? "–" : formatDuration(e.p95_ms)}
                    {e.baseline_ms !== null && ` (normal ${formatDuration(e.baseline_ms)})`}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Nenhuma rota de entrada passa pela causa: quem usa não sente.</p>
          )}
          {affected.length > 0 && (
            <div className="mt-4 border-t pt-3">
              <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">Afetados (doentes por causa dela)</h4>
              <ul className="space-y-1">
                {affected.map((a) => (
                  <li key={a.node} className="flex items-center justify-between gap-2 text-sm">
                    {a.node} <StateLabel state={a.state as HealthState} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {atRisk.length > 0 && (
            <p className="mt-3 text-xs text-muted-foreground">
              Em risco (dependem dela, mas seguem bem): {atRisk.join(", ")}
            </p>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Linha do tempo" icon={Clock} className="lg:col-span-2">
          <ol className="relative space-y-3 border-l pl-4">
            {data.events.map((e) => (
              <li key={`${e.at}${e.message}`} className="text-sm">
                <span className={cn("absolute -left-1.5 mt-1.5 size-3 rounded-full border-2 border-card", dotTone(e.kind, e.data))} />
                <span className="font-mono text-xs text-muted-foreground tabular">{clock(e.at)}</span>{" "}
                {e.message}
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Evidência nos traces" icon={Waypoints}>
          <p className="mb-3 text-xs text-muted-foreground">
            Onde os erros nasceram: spans com falha (5xx ou sem resposta) sem nenhum filho com falha.
          </p>
          {data.error_origins.length ? (
            <ul className="space-y-2">
              {data.error_origins.map((o) => (
                <li key={o.service} className="text-sm">
                  <div className="flex justify-between gap-2">
                    <span>{o.service}</span>
                    <span className="font-mono text-xs tabular">
                      {o.origins.toLocaleString("pt-BR")} · {formatPercent(o.share)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-muted">
                    <div className="h-full rounded-full bg-muted-foreground" style={{ width: `${o.share * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              Nenhum erro nos traces: um incidente de lentidão ou de serviço sem resposta.
            </p>
          )}
        </Card>
      </div>

      {data.comparison.length > 0 && <Comparison rows={data.comparison} />}
    </div>
  );
}

function Comparison({ rows }: { rows: EndpointComparison[] }) {
  return (
    <section className="rounded-xl border bg-card">
      <h2 className="flex items-center gap-2 px-4 pt-4 pb-2 text-sm font-medium">
        <ArrowRight className="size-4 text-muted-foreground" /> Antes, durante e depois
      </h2>
      <p className="px-4 pb-2 text-xs text-muted-foreground">
        Cada rota de entrada afetada: os 5 minutos antes de abrir, o pior minuto do incidente e os 5 minutos depois de
        resolver. Percentis exatos, dos spans gravados.
      </p>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Rota</TableHead>
              <TableHead>Período</TableHead>
              <TableHead className="text-right">Req/s</TableHead>
              <TableHead className="text-right">Erro</TableHead>
              <TableHead className="text-right">p95</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.flatMap((r) =>
              (
                [
                  ["5 min antes", r.before],
                  ["pior minuto", r.worst],
                  [r.after_complete ? "5 min depois" : "depois (ainda contando)", r.after],
                ] as [string, Period | null][]
              ).map(([label, p], i) => (
                <TableRow key={`${r.service}${r.route}${label}`}>
                  <TableCell className="font-mono text-xs whitespace-nowrap">{i === 0 ? r.route : ""}</TableCell>
                  <TableCell className="text-xs whitespace-nowrap text-muted-foreground">{label}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">{p ? formatRate(p.rps) : "–"}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">{p ? formatPercent(p.error_rate) : "–"}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular">
                    {p && p.p95_ms !== null ? formatDuration(p.p95_ms) : "–"}
                  </TableCell>
                </TableRow>
              )),
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

function Card({
  title,
  icon: Icon,
  className,
  children,
}: {
  title: string;
  icon: React.ElementType;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("rounded-xl border bg-card p-4", className)}>
      <h2 className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Icon className="size-4 text-muted-foreground" /> {title}
      </h2>
      {children}
    </section>
  );
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour12: false });
}

/** A cor do ponto na linha do tempo: o estado para onde a coisa foi (estado, nunca só cor: o texto está ao lado). */
function dotTone(kind: string, data: IncidentDetail["events"][number]["data"]): string {
  if (kind === "resolved") return "bg-success";
  if (kind === "opened") return "bg-destructive";
  if (kind === "node_state") {
    const to = (data as { to?: HealthState }).to;
    if (to === "healthy") return "bg-success";
    return to && STATE[to].tone === "warning" ? "bg-warning" : "bg-destructive";
  }
  return "bg-muted-foreground";
}

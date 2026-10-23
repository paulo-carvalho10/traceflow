"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Circle,
  CircleCheck,
  CircleX,
  FlaskConical,
  Gauge,
  LoaderCircle,
  Play,
  Square,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { IncidentBanner, SeverityBadge } from "@/components/incidents/badges";
import { LiveServiceMap } from "@/components/map/service-map-view";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useLive } from "@/hooks/use-live";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useNow } from "@/hooks/use-now";
import { ApiError, type Experiment, type ManualFault, type PlaygroundState, type Scenario, api } from "@/lib/api";
import type { Severity } from "@/lib/live";
import { type CycleStep, experimentCycle, incidentFor } from "@/lib/playground";
import { cn } from "@/lib/utils";

const DEMO_ENVIRONMENT = "demo"; // a loja de demonstração manda tudo neste ambiente

/**
 * O Incident Playground: quebrar a loja de demonstração de propósito e acompanhar o TraceFlow
 * detectar, apontar a causa, medir o impacto e resolver. Os botões ficam de um lado; a falha em
 * andamento, o ciclo do incidente e o mapa ao vivo, do outro. Numa coluna só (no celular), esse
 * lado vem depois dos botões, e a tela rola até ele quando uma falha começa.
 */
export function PlaygroundView({ projectId }: { projectId: number }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const now = useNow();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const isDemo = project.data?.is_demo ?? false;
  const playground = useQuery({ queryKey: ["playground"], queryFn: api.playground, refetchInterval: 2_000, enabled: isDemo });
  const { snapshot } = useLive(projectId, isDemo ? DEMO_ENVIRONMENT : undefined);
  const [duration, setDuration] = useState(180);
  // em duas colunas, a do mapa é estreita: o desenho vertical cabe com o texto legível
  const twoColumns = useMediaQuery("(min-width: 1280px)");
  const watchRef = useRef<HTMLDivElement>(null);

  const experiment = playground.data?.active ?? playground.data?.last ?? null;
  const incidents = useQuery({
    queryKey: ["incidents", projectId, "all"],
    queryFn: () => api.incidents(projectId),
    refetchInterval: experiment ? 3_000 : false,
    enabled: isDemo,
  });
  const incident = experiment ? incidentFor(experiment, incidents.data ?? []) : null;
  const live = snapshot?.incident && incident && snapshot.incident.id === incident.id ? snapshot.incident : null;

  const onState = (state: PlaygroundState) => {
    queryClient.setQueryData(["playground"], state);
    void queryClient.invalidateQueries({ queryKey: ["incidents", projectId] });
  };
  // numa coluna só, o ciclo fica abaixo dos botões: sem rolar, quem inicia não vê nada acontecer
  const onStarted = (state: PlaygroundState) => {
    onState(state);
    if (!twoColumns) watchRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const onError = (error: Error) => toast.error(error instanceof ApiError ? error.message : "Não deu certo. Tente de novo.");
  const start = useMutation({ mutationFn: (id: string) => api.startScenario(id, duration), onSuccess: onStarted, onError });
  const manual = useMutation({ mutationFn: (fault: ManualFault) => api.startFault(fault), onSuccess: onStarted, onError });
  const stop = useMutation({ mutationFn: api.stopFault, onSuccess: onState, onError });

  if (project.data && !isDemo) {
    const demo = projects.data?.find((p) => p.is_demo);
    return (
      <div className="space-y-3 px-4 py-16 text-center text-sm text-muted-foreground sm:px-8">
        <p>O Playground quebra a loja de demonstração de propósito, para você ver o TraceFlow em ação.</p>
        <p>Num projeto seu, as falhas são as de verdade.</p>
        {demo && (
          <Button asChild>
            <Link href={`/projects/${demo.id}/playground`}>Abrir o Playground da demonstração</Link>
          </Button>
        )}
      </div>
    );
  }
  if (!playground.data) {
    return (
      <div className="space-y-4 px-4 py-5 sm:px-8 sm:py-6">
        {playground.error instanceof ApiError ? (
          <p className="text-sm text-muted-foreground">{playground.error.message}</p>
        ) : (
          <Skeleton className="h-96 rounded-xl" />
        )}
      </div>
    );
  }

  const state = playground.data;
  const busy = state.active !== null || start.isPending || manual.isPending;
  return (
    <div className="space-y-6 px-4 py-5 sm:px-8 sm:py-6">
      <p className="max-w-3xl text-sm text-muted-foreground">
        Escolha um cenário pronto ou monte a sua falha, e acompanhe o TraceFlow detectar, apontar a causa, medir quem
        sente e resolver sozinho quando ela acabar. Uma falha por vez (a demonstração é compartilhada), e toda falha
        expira sozinha.
      </p>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <div className="space-y-6">
          <section className="space-y-3" aria-labelledby="cenarios">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="cenarios" className="flex items-center gap-2 text-sm font-medium">
                <FlaskConical className="size-4 text-muted-foreground" /> Cenários
              </h2>
              <Select value={String(duration)} onValueChange={(v) => setDuration(Number(v))}>
                <SelectTrigger className="w-40" aria-label="Duração da falha">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="60">Dura 1 min</SelectItem>
                  <SelectItem value="120">Dura 2 min</SelectItem>
                  <SelectItem value="180">Dura 3 min</SelectItem>
                  <SelectItem value="300">Dura 5 min</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {state.scenarios.map((s) => (
                <ScenarioCard key={s.id} scenario={s} disabled={busy} onStart={() => start.mutate(s.id)} />
              ))}
            </div>
          </section>
          <ManualFaultForm services={state.services} disabled={busy} duration={duration} onSubmit={(f) => manual.mutate(f)} />
          <TrafficControl state={state} now={now} onState={onState} onError={onError} />
        </div>

        {/* a margem de rolagem desconta o cabeçalho fixo do celular */}
        <div ref={watchRef} className="scroll-mt-20 space-y-4 lg:scroll-mt-6 xl:sticky xl:top-6 xl:self-start">
          {state.active && (
            <ActiveFault experiment={state.active} now={now} onStop={() => stop.mutate()} stopping={stop.isPending} />
          )}
          <CycleCard
            experiment={experiment}
            steps={experiment ? experimentCycle(experiment, incident, live, now) : null}
            incidentHref={incident ? `/projects/${projectId}/incidents/${incident.id}` : null}
          />
          {snapshot?.incident && <IncidentBanner incident={snapshot.incident} projectId={projectId} />}
          <section className="h-[560px] overflow-hidden rounded-xl border bg-card" aria-label="Mapa ao vivo">
            {snapshot ? (
              <LiveServiceMap
                snapshot={snapshot}
                direction={twoColumns ? "TB" : undefined}
                onOpen={(s) => router.push(`/projects/${projectId}/services/${encodeURIComponent(s)}?environment=${DEMO_ENVIRONMENT}`)}
              />
            ) : (
              <p className="p-6 text-sm text-muted-foreground">
                Esperando o retrato ao vivo… Sem tráfego, o mapa não tem o que desenhar: ligue o gerador de carga abaixo.
              </p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function ActiveFault({
  experiment,
  now,
  onStop,
  stopping,
}: {
  experiment: Experiment;
  now: number;
  onStop: () => void;
  stopping: boolean;
}) {
  const left = Math.max(0, Math.round((new Date(experiment.expires_at).getTime() - now) / 1000));
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm" role="status">
      <span className="flex items-center gap-1.5 font-medium text-destructive">
        <span className="relative flex size-2.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-destructive opacity-60" />
          <span className="relative inline-flex size-2.5 rounded-full bg-destructive" />
        </span>
        Falha em andamento
      </span>
      <span className="font-medium">{experiment.title}</span>
      <span className="font-mono text-muted-foreground tabular">
        termina sozinha em {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
      </span>
      <Button variant="outline" size="sm" className="ml-auto" onClick={onStop} disabled={stopping}>
        <Square className="size-3.5" /> Encerrar agora
      </Button>
    </div>
  );
}

function ScenarioCard({ scenario, disabled, onStart }: { scenario: Scenario; disabled: boolean; onStart: () => void }) {
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <h3 className="font-medium">{scenario.title}</h3>
      <p className="text-sm text-muted-foreground">{scenario.description}</p>
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        Esperado: causa <span className="font-mono text-foreground">{scenario.expect_cause.join(", ")}</span>
        <SeverityBadge severity={scenario.expect_severity as Severity} />
      </p>
      <p className="text-xs text-muted-foreground">{scenario.watch}</p>
      <Button size="sm" className="mt-auto self-start" onClick={onStart} disabled={disabled}>
        <Play className="size-3.5" /> Iniciar
      </Button>
    </article>
  );
}

function ManualFaultForm({
  services,
  disabled,
  duration,
  onSubmit,
}: {
  services: string[];
  disabled: boolean;
  duration: number;
  onSubmit: (fault: ManualFault) => void;
}) {
  const [service, setService] = useState(services[0] ?? "payments");
  const [kind, setKind] = useState<ManualFault["kind"]>("latency");
  const [value, setValue] = useState("800");

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const number = Number(value.replace(",", "."));
    onSubmit({
      service: service as ManualFault["service"],
      kind,
      latency_ms: kind === "latency" ? number : 1000,
      error_rate: kind === "errors" ? number / 100 : 0.3, // a tela fala em %, a API em fração
      duration_s: duration,
    });
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-xl border bg-card p-4">
      <h2 className="flex items-center gap-2 text-sm font-medium">
        <Wrench className="size-4 text-muted-foreground" /> Falha manual
      </h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Serviço</Label>
          <Select value={service} onValueChange={setService}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {services.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Falha</Label>
          <Select
            value={kind}
            onValueChange={(v) => {
              setKind(v as ManualFault["kind"]);
              setValue(v === "latency" ? "800" : "30");
            }}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="latency">Lentidão</SelectItem>
              <SelectItem value="errors">Erros</SelectItem>
              <SelectItem value="down">Fora do ar</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {kind !== "down" && (
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">{kind === "latency" ? "Atraso (ms, 100 a 5000)" : "Erro (%, 1 a 100)"}</Label>
            <Input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" required />
          </div>
        )}
      </div>
      <Button type="submit" size="sm" variant="outline" disabled={disabled}>
        <Play className="size-3.5" /> Injetar
      </Button>
    </form>
  );
}

function TrafficControl({
  state,
  now,
  onState,
  onError,
}: {
  state: PlaygroundState;
  now: number;
  onState: (s: PlaygroundState) => void;
  onError: (e: Error) => void;
}) {
  const { traffic } = state;
  const [rps, setRps] = useState(traffic.rps);
  const [checkout, setCheckout] = useState(Math.round(traffic.checkout_ratio * 100));
  const apply = useMutation({ mutationFn: () => api.setTraffic(rps, checkout / 100), onSuccess: onState, onError });
  const reset = useMutation({
    mutationFn: api.resetTraffic,
    onSuccess: (s: PlaygroundState) => {
      setRps(s.traffic.rps);
      setCheckout(Math.round(s.traffic.checkout_ratio * 100));
      onState(s);
    },
    onError,
  });
  const left = traffic.expires_at ? Math.max(0, Math.round((new Date(traffic.expires_at).getTime() - now) / 1000)) : 0;

  return (
    <section className="space-y-3 rounded-xl border bg-card p-4" aria-labelledby="trafego">
      <h2 id="trafego" className="flex items-center gap-2 text-sm font-medium">
        <Gauge className="size-4 text-muted-foreground" /> Tráfego
      </h2>
      <p className="text-xs text-muted-foreground">
        Agora: {traffic.rps} req/s, {Math.round(traffic.checkout_ratio * 100)}% compras.{" "}
        {traffic.custom
          ? `Volta ao padrão (${traffic.default_rps} req/s, ${Math.round(traffic.default_checkout_ratio * 100)}%) em ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}.`
          : "É o padrão."}
      </p>
      <label className="block space-y-1 text-sm">
        <span className="flex justify-between text-xs text-muted-foreground">
          Requisições por segundo <span className="font-mono text-foreground tabular">{rps}</span>
        </span>
        <input type="range" min={1} max={60} value={rps} onChange={(e) => setRps(Number(e.target.value))} className="w-full accent-primary" />
      </label>
      <label className="block space-y-1 text-sm">
        <span className="flex justify-between text-xs text-muted-foreground">
          Fração de compras <span className="font-mono text-foreground tabular">{checkout}%</span>
        </span>
        <input type="range" min={0} max={90} value={checkout} onChange={(e) => setCheckout(Number(e.target.value))} className="w-full accent-primary" />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => apply.mutate()} disabled={apply.isPending}>
          Aplicar
        </Button>
        {traffic.custom && (
          <Button size="sm" variant="ghost" onClick={() => reset.mutate()} disabled={reset.isPending}>
            Voltar ao padrão
          </Button>
        )}
      </div>
    </section>
  );
}

const STEP_ICON = {
  done: CircleCheck,
  current: LoaderCircle,
  pending: Circle,
  missed: TriangleAlert,
} as const;

function CycleCard({
  experiment,
  steps,
  incidentHref,
}: {
  experiment: Experiment | null;
  steps: CycleStep[] | null;
  incidentHref: string | null;
}) {
  return (
    <section className="rounded-xl border bg-card p-4" aria-labelledby="ciclo">
      <h2 id="ciclo" className="mb-1 text-sm font-medium">
        O ciclo do incidente
      </h2>
      {!experiment || !steps ? (
        <p className="text-sm text-muted-foreground">
          Escolha um cenário ou monte uma falha. O ciclo aparece aqui, passo a passo: a falha, a detecção, a causa, a
          recuperação e a resolução.
        </p>
      ) : (
        <>
          <p className="mb-3 text-xs text-muted-foreground">{experiment.title}</p>
          <ol className="space-y-2.5">
            {steps.map((step) => {
              const Icon = step.ok === false ? CircleX : STEP_ICON[step.state];
              return (
                <li key={step.key} className="flex items-start gap-2.5 text-sm">
                  <Icon
                    className={cn(
                      "mt-0.5 size-4 shrink-0",
                      step.ok === false && "text-warning",
                      step.ok !== false && step.state === "done" && "text-success",
                      step.state === "current" && "animate-spin text-primary",
                      step.state === "pending" && "text-muted-foreground/50",
                      step.state === "missed" && "text-warning",
                    )}
                  />
                  <span className={cn("min-w-0 flex-1", step.state === "pending" && "text-muted-foreground")}>
                    <span className="font-medium">{step.label}</span>
                    {step.detail && <span className="text-muted-foreground"> · {step.detail}</span>}
                  </span>
                  {step.at && (
                    <span className="shrink-0 font-mono text-xs text-muted-foreground tabular">
                      {new Date(step.at).toLocaleTimeString("pt-BR", { hour12: false })}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
          {incidentHref && (
            <Link href={incidentHref} className="mt-3 inline-block text-xs font-medium text-primary hover:underline">
              Ver o incidente completo: linha do tempo, evidência e antes / depois →
            </Link>
          )}
        </>
      )}
    </section>
  );
}

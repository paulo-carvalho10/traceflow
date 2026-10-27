import { STATE } from "@/lib/incidents";
import type { HealthState, LiveSnapshot } from "@/lib/live";
import { cn } from "@/lib/utils";

/** A saúde de um serviço agora: a do retrato ao vivo, ou "parado" quando não houve tráfego. */
export type ServiceState = HealthState | "idle";

export function serviceState(name: string, snapshot: LiveSnapshot | null): ServiceState {
  const health = snapshot?.health[name]?.state;
  if (health) return health;
  return snapshot?.services.some((s) => s.name === name) ? "healthy" : "idle";
}

const DOT: Record<ServiceState, string> = {
  healthy: "bg-success",
  degraded: "bg-warning",
  failing: "bg-destructive",
  unresponsive: "bg-destructive",
  idle: "bg-faint",
};

const TEXT: Record<ServiceState, string> = {
  healthy: "text-muted-foreground",
  degraded: "text-warning",
  failing: "text-destructive",
  unresponsive: "text-destructive",
  idle: "text-faint",
};

export function stateLabel(state: ServiceState): string {
  return state === "idle" ? "sem tráfego" : STATE[state].label;
}

/** Um ponto colorido, sempre com o nome do estado para leitores de tela e na dica. */
export function HealthDot({ state, className }: { state: ServiceState; className?: string }) {
  return (
    <span className={cn("inline-block size-1.5 shrink-0 rounded-full", DOT[state], className)} title={stateLabel(state)}>
      <span className="sr-only">{stateLabel(state)}</span>
    </span>
  );
}

/** O ponto e o texto: em tabelas, o estado nunca é só a cor. */
export function HealthLabel({ state }: { state: ServiceState }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", TEXT[state])}>
      <span className={cn("size-1.5 shrink-0 rounded-full", DOT[state])} aria-hidden />
      {stateLabel(state)}
    </span>
  );
}

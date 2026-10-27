import { CircleCheck, Info, OctagonAlert, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { SEVERITY, STATE, TONE_TEXT, formatElapsed, recovery } from "@/lib/incidents";
import type { HealthState, LiveIncident, Severity } from "@/lib/live";
import { cn } from "@/lib/utils";

const SEVERITY_STYLE = {
  critical: "border-destructive/40 bg-destructive/10 text-destructive",
  warning: "border-warning/40 bg-warning/10 text-warning",
  neutral: "border-border bg-muted text-muted-foreground",
} as const;

/** "SEV1 · crítico", com ícone: a severidade nunca é só a cor. */
export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const { label, tone, hint } = SEVERITY[severity];
  const Icon = tone === "critical" ? OctagonAlert : tone === "warning" ? TriangleAlert : Info;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap",
        SEVERITY_STYLE[tone],
        className,
      )}
      title={hint}
    >
      <Icon className="size-3.5" /> {severity} · {label}
    </span>
  );
}

export function StateLabel({ state, className }: { state: HealthState; className?: string }) {
  const { label, tone } = STATE[state];
  const Icon = tone === "ok" ? CircleCheck : tone === "warning" ? TriangleAlert : OctagonAlert;
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", TONE_TEXT[tone], className)}>
      <Icon className="size-3.5" /> {label}
    </span>
  );
}

/**
 * A faixa de "há um incidente aberto agora", com o essencial e o caminho para o detalhe.
 * Em recuperação (tudo saudável, esperando a carência para resolver), ela fica verde e conta
 * o tempo: sem isso, o incidente parece "travado" aberto por 30 s depois de a falha acabar.
 */
export function IncidentBanner({ incident, projectId }: { incident: LiveIncident; projectId: number }) {
  const critical = SEVERITY[incident.severity].tone === "critical";
  const healing = recovery(incident);
  return (
    <Link
      href={`/projects/${projectId}/incidents/${incident.id}`}
      className={cn(
        "relative flex flex-wrap items-center gap-x-3 gap-y-1 overflow-hidden rounded-lg border px-4 py-3 text-sm transition-colors hover:bg-accent/40",
        healing
          ? "border-success/50 bg-success/5"
          : critical
            ? "border-destructive/50 bg-destructive/5"
            : "border-warning/40 bg-warning/5",
      )}
      role={healing ? "status" : "alert"}
    >
      {healing ? (
        <span className="inline-flex items-center gap-1 rounded-md border border-success/40 bg-success/10 px-1.5 py-0.5 text-xs font-medium text-success">
          <CircleCheck className="size-3.5" /> Em recuperação
        </span>
      ) : (
        <SeverityBadge severity={incident.severity} />
      )}
      <span className="font-medium">{incident.title}</span>
      <span className="text-muted-foreground">
        {healing
          ? `tudo saudável há ${healing.healthyFor} s · resolve em ${healing.resolvesIn} s, se continuar assim`
          : `aberto há ${formatElapsed(incident.opened_at)}`}
        {!healing && incident.endpoints.length > 0 && ` · afeta ${incident.endpoints.map((e) => e.route).join(", ")}`}
      </span>
      <span className="ml-auto text-xs font-medium text-primary">Ver incidente →</span>
      {healing && (
        <span
          className="absolute bottom-0 left-0 h-0.5 bg-success transition-[width] duration-1000 ease-linear"
          style={{ width: `${healing.progress * 100}%` }}
          aria-hidden
        />
      )}
    </Link>
  );
}

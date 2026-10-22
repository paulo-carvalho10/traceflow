import { CircleCheck, Info, OctagonAlert, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { SEVERITY, STATE, TONE_TEXT, formatElapsed } from "@/lib/incidents";
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

/** A faixa de "há um incidente aberto agora", com o essencial e o caminho para o detalhe. */
export function IncidentBanner({ incident, projectId }: { incident: LiveIncident; projectId: number }) {
  const critical = SEVERITY[incident.severity].tone === "critical";
  return (
    <Link
      href={`/projects/${projectId}/incidents/${incident.id}`}
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border px-4 py-3 text-sm transition-colors hover:bg-accent/40",
        critical ? "border-destructive/50 bg-destructive/5" : "border-warning/40 bg-warning/5",
      )}
      role="alert"
    >
      <SeverityBadge severity={incident.severity} />
      <span className="font-medium">{incident.title}</span>
      <span className="text-muted-foreground">
        aberto há {formatElapsed(incident.opened_at)}
        {incident.endpoints.length > 0 && ` · afeta ${incident.endpoints.map((e) => e.route).join(", ")}`}
      </span>
      <span className="ml-auto text-xs font-medium text-primary">Ver incidente →</span>
    </Link>
  );
}

import type { Rule } from "@/lib/api";
import type { HealthState, Severity } from "@/lib/live";

/**
 * Como os incidentes aparecem na tela. Severidade e estado são cores de STATUS (reservadas:
 * nenhum serviço usa vermelho ou âmbar como cor própria) e sempre vêm com texto e ícone.
 */

export const SEVERITY: Record<Severity, { label: string; tone: "critical" | "warning" | "neutral"; hint: string }> = {
  SEV1: { label: "crítico", tone: "critical", hint: "uma rota de entrada com 25% ou mais de erro, ou fora do ar" },
  SEV2: { label: "alto", tone: "warning", hint: "uma rota de entrada com 5% ou mais de erro, ou duas vezes mais lenta" },
  SEV3: { label: "baixo", tone: "neutral", hint: "uma dependência doente, mas quem usa não sente" },
};

export const STATE: Record<HealthState, { label: string; tone: "ok" | "warning" | "critical" }> = {
  healthy: { label: "saudável", tone: "ok" },
  degraded: { label: "degradado", tone: "warning" },
  failing: { label: "falhando", tone: "critical" },
  unresponsive: { label: "sem resposta", tone: "critical" },
};

export const TONE_TEXT = {
  critical: "text-destructive",
  warning: "text-warning",
  neutral: "text-muted-foreground",
  ok: "text-success",
} as const;

export const TONE_BORDER = {
  critical: "border-destructive",
  warning: "border-warning",
  neutral: "border-border",
  ok: "border-border",
} as const;

const METRIC: Record<Rule["metric"], string> = {
  error_rate: "a taxa de erro",
  p95_ms: "o p95",
  p99_ms: "o p99",
  rps: "o tráfego",
  availability: "a disponibilidade",
};

/** "Se a taxa de erro de qualquer serviço for ≥ 5%, com ao menos 20 requisições em 10 s" */
export function describeRule(rule: Pick<Rule, "target" | "metric" | "operator" | "threshold" | "relative" | "min_requests">): string {
  const who = rule.target === "*" ? "qualquer serviço" : rule.target;
  const op = rule.operator === ">=" ? "≥" : "≤";
  let limit: string;
  if (rule.relative) {
    limit = `${op} ${decimal(rule.threshold)}× a linha de base (e pelo menos 50 ms acima dela)`;
  } else if (rule.metric === "error_rate" || rule.metric === "availability") {
    limit = `${op} ${decimal(rule.threshold * 100)}%`;
  } else if (rule.metric === "rps") {
    limit = `${op} ${decimal(rule.threshold)}/s`;
  } else {
    limit = `${op} ${decimal(rule.threshold)} ms`;
  }
  return `Se ${METRIC[rule.metric]} de ${who} for ${limit}, com ao menos ${rule.min_requests} requisições em 10 s`;
}

function decimal(value: number): string {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(value);
}

/** Quanto tempo entre dois instantes, do jeito que se fala: "45 s", "3 min 12 s", "1 h 5 min". */
export function formatElapsed(from: string | number, to: string | number = Date.now()): string {
  const seconds = Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return seconds % 60 ? `${minutes} min ${seconds % 60} s` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
}

/** O período da busca de traces que cobre o incidente (a busca trabalha com períodos prontos). */
export function tracesPeriodFor(openedAt: string, now = Date.now()): "1h" | "6h" | "24h" | "3d" {
  const hours = (now - new Date(openedAt).getTime()) / 3_600_000;
  if (hours < 0.9) return "1h";
  if (hours < 5.5) return "6h";
  if (hours < 23) return "24h";
  return "3d";
}

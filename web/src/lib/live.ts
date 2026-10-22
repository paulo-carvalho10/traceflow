/**
 * O retrato ao vivo que o processador publica a cada segundo (backend: live/aggregator.py).
 * Ele chega pelo WebSocket, não por REST, então não está no OpenAPI: os tipos ficam aqui.
 */

export type LivePoint = { t: number; rps: number; errors: number; p95_ms: number | null };

export type LiveStats = {
  rps: number;
  error_rate: number;
  availability: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  requests: number;
  entry_rps: number; // as requisições que entraram no sistema por aqui (spans raiz)
  series: LivePoint[]; // um ponto por segundo, do último minuto
};

export type LiveService = LiveStats & { name: string };

/** Uma ligação do mapa: medida do lado de quem chama (spans CLIENT). Falha = 5xx ou sem resposta. */
export type LiveEdge = {
  source: string;
  target: string; // o serviço, ou o próprio endereço quando ninguém o atendeu com um span
  address: string;
  virtual: boolean;
  rps: number;
  error_rate: number;
  p50_ms: number | null;
  p95_ms: number | null;
  requests: number;
};

export type LiveSnapshot = {
  project_id: number;
  environment: string;
  generated_at: string;
  window: { from: number; to: number; seconds: number };
  entry: LiveStats | null; // as requisições que entraram no sistema (spans raiz)
  services: LiveService[];
  edges: LiveEdge[];
  unresponsive: string[]; // serviços chamados que pararam de atender (as chamadas falham e eles somem)
  entrypoints: LiveEntrypoint[];
  health: Record<string, { state: HealthState; reason: string }>; // só os nós que não estão saudáveis
  incident: LiveIncident | null;
};

/** Uma rota de entrada ("POST /checkout"): o que quem usa sente, e por onde ela passa. */
export type LiveEntrypoint = {
  route: string;
  service: string;
  rps: number;
  error_rate: number;
  p95_ms: number | null;
  requests: number;
  nodes: string[];
};

export type HealthState = "healthy" | "degraded" | "failing" | "unresponsive";
export type Severity = "SEV1" | "SEV2" | "SEV3";

export type IncidentCause = { node: string; state: HealthState; reason: string; own: boolean; virtual: boolean };

/** O incidente aberto, no retrato de cada segundo (o mesmo que fica gravado, ao vivo). */
export type LiveIncident = {
  id: string;
  status: "open" | "resolved";
  severity: Severity;
  peak_severity: Severity;
  title: string;
  opened_at: string;
  causes: IncidentCause[];
  affected: { node: string; state: HealthState; reason: string }[];
  at_risk: string[];
  endpoints: { route: string; service: string; rps: number; error_rate: number; p95_ms: number | null; baseline_ms: number | null }[];
};

export type LiveMessage =
  | { type: "snapshot"; data: LiveSnapshot }
  | { type: "subscribed"; project_id: number; environment: string }
  | { type: "idle" } // o processamento está no ar, mas nada deste projeto e ambiente no último minuto
  | { type: "error"; detail: string };

/** A régua de alerta da taxa de falha, a mesma da regra padrão de "degradado" (capítulo 11). */
export const ERROR_ALERT = 0.05;

/** Sem retrato e sem aviso por mais que isto: o processamento parou de mandar sinal. */
export const STALE_AFTER_MS = 5_000;

export type LiveStatus = "conectando" | "ao vivo" | "sem tráfego" | "sem dados novos" | "reconectando";

/**
 * O estado que a tela mostra, a partir do que chegou e de quando chegou. A cada segundo
 * chega um retrato (há tráfego) ou um aviso "idle" (não há); o mais recente decide.
 * Se nenhum dos dois chega, o problema não é falta de tráfego: o processamento parou.
 */
export function liveStatus({
  connection,
  subscribedAt,
  snapshotAt,
  idleAt,
  now,
}: {
  connection: "conectando" | "assinado" | "reconectando";
  subscribedAt: number | null;
  snapshotAt: number | null;
  idleAt: number | null;
  now: number;
}): LiveStatus {
  if (connection !== "assinado") return connection;
  const lastSignal = Math.max(snapshotAt ?? -Infinity, idleAt ?? -Infinity, subscribedAt ?? -Infinity);
  if (now - lastSignal > STALE_AFTER_MS) return "sem dados novos";
  if (snapshotAt === null && idleAt === null) return "conectando"; // assinou há pouco: o 1º sinal chega em até 1 s
  return (snapshotAt ?? -Infinity) >= (idleAt ?? -Infinity) ? "ao vivo" : "sem tráfego";
}

/** Espera antes de reconectar: 1 s, 2 s, 4 s... até 15 s (backoff exponencial). */
export function reconnectDelay(attempt: number): number {
  return Math.min(15_000, 1_000 * 2 ** attempt);
}

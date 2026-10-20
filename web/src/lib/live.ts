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
  series: LivePoint[]; // um ponto por segundo, do último minuto
};

export type LiveService = LiveStats & { name: string };

export type LiveSnapshot = {
  project_id: number;
  environment: string;
  generated_at: string;
  window: { from: number; to: number; seconds: number };
  entry: LiveStats | null; // as requisições que entraram no sistema (spans raiz)
  services: LiveService[];
};

export type LiveMessage =
  | { type: "snapshot"; data: LiveSnapshot }
  | { type: "subscribed"; project_id: number; environment: string }
  | { type: "error"; detail: string };

/** O retrato é velho se o processador parou de publicar (sem tráfego, ou fora do ar). */
export const STALE_AFTER_MS = 5_000;

/** Espera antes de reconectar: 1 s, 2 s, 4 s... até 15 s (backoff exponencial). */
export function reconnectDelay(attempt: number): number {
  return Math.min(15_000, 1_000 * 2 ** attempt);
}

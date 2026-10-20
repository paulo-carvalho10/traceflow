/**
 * O cliente da API do TraceFlow.
 *
 * Os tipos vêm de ./api-types.ts, gerado a partir do OpenAPI que o FastAPI publica
 * (`npm run api:types`): se um modelo Pydantic mudar, o TypeScript acusa aqui antes de rodar.
 *
 * Toda chamada leva `credentials: "include"`: o navegador manda o cookie de sessão, que é
 * HttpOnly. O JavaScript nunca vê o token; ele só pede para o navegador anexá-lo.
 */
import type { components } from "./api-types";

type Schemas = components["schemas"];
export type User = Schemas["UserOut"];
export type Project = Schemas["ProjectOut"];
export type ApiKey = Schemas["KeyOut"];
export type NewApiKey = Schemas["NewKeyOut"];
export type Environment = Schemas["EnvironmentOut"];
export type Service = Schemas["ServiceOut"];
export type TraceSummary = Schemas["TraceSummary"];
export type TracePage = Schemas["TracePage"];
export type Trace = Schemas["TraceOut"];
export type Span = Schemas["SpanOut"];

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "content-type": "application/json", ...init.headers },
  });
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(body, response.status));
  return body as T;
}

/** O FastAPI responde `{"detail": "texto"}`, ou uma lista de erros de validação (422). */
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const field = first.loc?.at(-1);
    return field ? `${String(field)}: ${first.msg}` : (first.msg ?? `erro ${status}`);
  }
  return `erro ${status}`;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export type TraceFilters = {
  environment?: string;
  service?: string;
  operation?: string;
  status?: "error" | "ok";
  min_duration_ms?: number;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
};

function query(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : "";
}

export const api = {
  me: () => request<User>("/api/auth/me"),
  login: (email: string, password: string) => request<User>("/api/auth/login", json({ email, password })),
  register: (name: string, email: string, password: string) =>
    request<User>("/api/auth/register", json({ name, email, password })),
  demo: () => request<User>("/api/auth/demo", { method: "POST" }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  projects: () => request<Project[]>("/api/projects"),
  project: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (name: string) => request<Project>("/api/projects", json({ name })),

  keys: (projectId: number) => request<ApiKey[]>(`/api/projects/${projectId}/keys`),
  createKey: (projectId: number, name: string) =>
    request<NewApiKey>(`/api/projects/${projectId}/keys`, json({ name })),
  revokeKey: (projectId: number, keyId: number) =>
    request<void>(`/api/projects/${projectId}/keys/${keyId}`, { method: "DELETE" }),

  environments: (projectId: number) => request<Environment[]>(`/api/projects/${projectId}/environments`),
  services: (projectId: number, environment?: string) =>
    request<Service[]>(`/api/projects/${projectId}/services${query({ environment })}`),

  traces: (projectId: number, filters: TraceFilters) =>
    request<TracePage>(`/api/projects/${projectId}/traces${query(filters)}`),
  trace: (projectId: number, traceId: string, around?: string) =>
    request<Trace>(`/api/projects/${projectId}/traces/${traceId}${query({ around })}`),
};

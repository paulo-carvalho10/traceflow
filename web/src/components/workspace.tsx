"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useContext, useMemo } from "react";

import { useLive } from "@/hooks/use-live";
import { type Environment, type Project, api } from "@/lib/api";
import type { LiveSnapshot, LiveStatus } from "@/lib/live";

/**
 * O espaço de trabalho de um projeto: o ambiente, o período e a conexão ao vivo, iguais em
 * todas as telas. Ficam na URL (?environment=demo&range=6h), então um link copiado abre a
 * mesma visão, e trocar de tela não perde a escolha. A conexão ao vivo é uma só, aqui: o
 * cabeçalho mostra o estado dela, e as telas leem o mesmo retrato.
 */

export const RANGES = {
  "15m": { minutes: 15, label: "Últimos 15 min", short: "15 min" },
  "1h": { minutes: 60, label: "Última hora", short: "1 h" },
  "6h": { minutes: 360, label: "Últimas 6 h", short: "6 h" },
  "24h": { minutes: 1440, label: "Últimas 24 h", short: "24 h" },
  "3d": { minutes: 4320, label: "Últimos 3 dias", short: "3 dias" },
} as const;
export type Range = keyof typeof RANGES;
const DEFAULT_RANGE: Range = "1h";

type Workspace = {
  projectId: number;
  project: Project | undefined;
  environment: string | undefined;
  environments: Environment[];
  environmentsLoading: boolean;
  setEnvironment: (name: string) => void;
  range: Range;
  setRange: (range: Range) => void;
  /** O período como datas. O "agora" anda de 30 em 30 s, e as consultas que dependem dele refazem. */
  window: { since: string; until: string } | null;
  live: { snapshot: LiveSnapshot | null; status: LiveStatus };
  /** Acrescenta o ambiente e o período a um link interno, para a escolha seguir junto. */
  scoped: (href: string) => string;
};

const WorkspaceContext = createContext<Workspace | null>(null);

export function WorkspaceProvider({ projectId, children }: { projectId: number; children: React.ReactNode }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });
  const environments = useQuery({ queryKey: ["environments", projectId], queryFn: () => api.environments(projectId) });
  // sem escolha, vale o ambiente com tráfego mais recente (a API os devolve nessa ordem)
  const environment = params.get("environment") ?? environments.data?.[0]?.name;
  const asked = params.get("range");
  const range: Range = asked && asked in RANGES ? (asked as Range) : DEFAULT_RANGE;

  const timeWindow = useQuery({
    queryKey: ["window", range],
    queryFn: () => {
      const until = new Date();
      return {
        until: until.toISOString(),
        since: new Date(until.getTime() - RANGES[range].minutes * 60_000).toISOString(),
      };
    },
    refetchInterval: 30_000,
    staleTime: 0,
  });
  const { snapshot, status } = useLive(projectId, environment);

  const value = useMemo<Workspace>(() => {
    function replace(key: string, val: string | null) {
      const next = new URLSearchParams(params);
      if (val === null) next.delete(key);
      else next.set(key, val);
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    }
    return {
      projectId,
      project: project.data,
      environment,
      environments: environments.data ?? [],
      environmentsLoading: environments.isPending,
      setEnvironment: (name) => replace("environment", name),
      range,
      setRange: (next) => replace("range", next === DEFAULT_RANGE ? null : next),
      window: timeWindow.data ?? null,
      live: { snapshot, status },
      scoped: (href) => {
        const keep = new URLSearchParams();
        const env = params.get("environment");
        if (env) keep.set("environment", env);
        if (range !== DEFAULT_RANGE) keep.set("range", range);
        const query = keep.toString();
        if (!query) return href;
        return href.includes("?") ? `${href}&${query}` : `${href}?${query}`;
      },
    };
  }, [projectId, project.data, environment, environments.data, environments.isPending, range, timeWindow.data, snapshot, status, params, router, pathname]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const workspace = useContext(WorkspaceContext);
  if (!workspace) throw new Error("useWorkspace fora de um projeto (WorkspaceProvider)");
  return workspace;
}

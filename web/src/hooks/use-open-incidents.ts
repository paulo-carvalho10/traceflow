"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { type IncidentSummary, api } from "@/lib/api";
import { SEVERITY } from "@/lib/incidents";
import type { Severity } from "@/lib/live";

/**
 * Os incidentes abertos do projeto, para o menu e para os avisos no canto da tela.
 *
 * É uma consulta leve a cada 5 s, e não o WebSocket: o aviso vale para qualquer tela e
 * qualquer ambiente, e o retrato ao vivo é de um ambiente só. O detalhe segundo a segundo
 * continua vindo pelo WebSocket nas telas que o mostram.
 *
 * Com `notify` falso, a lista continua valendo para o menu, mas sem avisos: o Playground
 * já mostra a abertura e a resolução no próprio ciclo, e o aviso cobriria o mapa.
 */
export function useOpenIncidents(projectId: number, { notify = true } = {}) {
  const router = useRouter();
  const open = useQuery({
    queryKey: ["incidents", projectId, "open"],
    queryFn: () => api.incidents(projectId, { status: "open" }),
    refetchInterval: 5_000,
  });
  const known = useRef<Map<string, IncidentSummary> | null>(null);

  useEffect(() => {
    if (!open.data) return;
    const now = new Map(open.data.map((i) => [i.id, i]));
    const before = known.current;
    known.current = now;
    if (before === null || !notify) return; // a primeira leitura não avisa: o que já estava aberto não é novidade
    for (const [id, incident] of now) {
      if (!before.has(id)) {
        const sev = incident.severity as Severity;
        const show = SEVERITY[sev].tone === "critical" ? toast.error : toast.warning;
        show(`${sev} · ${incident.title}`, {
          description: `Incidente aberto em ${incident.environment}`,
          action: { label: "Ver", onClick: () => router.push(`/projects/${projectId}/incidents/${id}`) },
          duration: 10_000,
        });
      }
    }
    for (const [id, incident] of before) {
      if (!now.has(id)) {
        toast.success(`Resolvido: ${incident.title}`, {
          description: "Tudo saudável há 30 s",
          action: { label: "Ver", onClick: () => router.push(`/projects/${projectId}/incidents/${id}`) },
        });
      }
    }
  }, [open.data, projectId, router, notify]);

  const worst = open.data?.reduce<Severity | null>((acc, i) => {
    const sev = i.severity as Severity;
    return acc === null || sev < acc ? sev : acc; // "SEV1" < "SEV2": a mais grave
  }, null);
  return { incidents: open.data ?? [], worst };
}

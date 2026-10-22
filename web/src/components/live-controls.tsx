"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { LiveStatus } from "@/hooks/use-live";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * O ambiente escolhido, guardado na URL (?environment=). Sem escolha, vale o ambiente com
 * tráfego mais recente (a API devolve os ambientes do mais recente para o mais antigo).
 */
export function useEnvironment(projectId: number) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const environments = useQuery({
    queryKey: ["environments", projectId],
    queryFn: () => api.environments(projectId),
  });
  const chosen = params.get("environment") ?? environments.data?.[0]?.name;

  function choose(name: string) {
    const next = new URLSearchParams(params);
    next.set("environment", name);
    router.replace(`${pathname}?${next}`, { scroll: false });
  }

  return { environment: chosen, environments: environments.data ?? [], loading: environments.isPending, choose };
}

export function EnvironmentSelect({
  value,
  options,
  onChange,
}: {
  value: string | undefined;
  options: { name: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange} disabled={options.length === 0}>
      <SelectTrigger className="w-48">
        <SelectValue placeholder="Sem ambientes ainda" />
      </SelectTrigger>
      <SelectContent>
        {options.map((env) => (
          <SelectItem key={env.name} value={env.name}>
            Ambiente: {env.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

const STATUS_STYLE: Record<LiveStatus, string> = {
  "ao vivo": "bg-success",
  "sem tráfego": "bg-muted-foreground", // não é problema: só não chegou nada
  conectando: "bg-muted-foreground",
  reconectando: "bg-warning",
  "sem dados novos": "bg-warning", // é problema: o processamento parou de mandar sinal
};

const STATUS_LABEL: Record<LiveStatus, string> = {
  "ao vivo": "Ao vivo · atualiza a cada segundo",
  "sem tráfego": "Conectado · sem tráfego no último minuto",
  conectando: "Conectando…",
  reconectando: "Reconectando…",
  "sem dados novos": "Sem sinal do processamento há mais de 5 s",
};

/** O estado da conexão ao vivo, sempre com texto: estado nunca é só a cor do ponto. */
export function LiveBadge({ status }: { status: LiveStatus }) {
  return (
    <span className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
      <span className="relative flex size-2.5">
        {status === "ao vivo" && (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
        )}
        <span className={cn("relative inline-flex size-2.5 rounded-full", STATUS_STYLE[status])} />
      </span>
      {STATUS_LABEL[status]}
    </span>
  );
}

/**
 * No lugar dos números ao vivo quando não há o que mostrar. Diz o porquê, em vez de deixar
 * os blocos "carregando" para sempre: falta de tráfego não é o mesmo que sistema parado.
 */
export function LiveEmpty({ status, children }: { status: LiveStatus; children: ReactNode }) {
  return (
    <p className="col-span-full rounded-xl border border-dashed bg-card px-4 py-6 text-sm text-muted-foreground">
      {status === "sem dados novos"
        ? "O processamento parou de mandar sinal, então não há números ao vivo agora. Eles voltam sozinhos quando o processamento voltar."
        : children}
    </p>
  );
}

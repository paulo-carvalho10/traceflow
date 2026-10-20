"use client";

import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";

/**
 * O que toda tela tem por baixo:
 * - o QueryClient do TanStack Query: o cache das respostas da API, compartilhado entre telas;
 * - os avisos (toasts) e as dicas (tooltips).
 */
export function Providers({ children }: { children: React.ReactNode }) {
  // useState garante um QueryClient por aba do navegador, criado uma vez só
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000, // por 10 s, a mesma consulta usa o cache em vez de ir à API de novo
            refetchOnWindowFocus: false,
            retry: (failures, error) =>
              // 401, 403 e 404 não mudam tentando de novo; erro de rede ou 5xx, sim
              !(error instanceof ApiError && error.status < 500) && failures < 2,
          },
        },
        // erro em qualquer ação (criar, revogar...) vira um aviso na tela, menos nas que mostram
        // o erro elas mesmas (meta.silent, como o formulário de login)
        mutationCache: new MutationCache({
          onError: (error, _variables, _result, mutation) => {
            if (!mutation.meta?.silent) toast.error(error.message);
          },
        }),
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={200}>
        {children}
        <Toaster theme="dark" richColors position="bottom-right" />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { ApiError, api } from "@/lib/api";

/**
 * Quem está logado. Se ninguém estiver (a API respondeu 401), manda para o login,
 * guardando para onde a pessoa queria ir.
 *
 * A proteção de verdade é a API: ela recusa tudo sem cookie válido. Este hook só evita
 * mostrar uma tela vazia para quem não entrou.
 */
export function useSession() {
  const router = useRouter();
  const pathname = usePathname();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60_000 });
  const unauthorized = me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    if (unauthorized) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthorized, router, pathname]);

  return me;
}

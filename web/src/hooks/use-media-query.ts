"use client";

import { useSyncExternalStore } from "react";

/**
 * Se a tela atende a uma media query agora (ex.: "(max-width: 640px)"), e reage quando muda.
 * useSyncExternalStore lê a resposta do navegador direto, sem estado copiado nem efeito; no
 * servidor (sem tela), responde false.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const media = window.matchMedia(query);
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

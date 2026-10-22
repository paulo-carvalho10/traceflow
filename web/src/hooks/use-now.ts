"use client";

import { useEffect, useState } from "react";

/** O "agora", atualizado a cada intervalo: para contadores como "aberto há 3 min 12 s". */
export function useNow(intervalMs = 1_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

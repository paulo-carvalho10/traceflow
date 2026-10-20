"use client";

import { useEffect, useState } from "react";

import { API_URL, api } from "@/lib/api";
import { type LiveMessage, type LiveSnapshot, STALE_AFTER_MS, reconnectDelay } from "@/lib/live";

export type LiveStatus = "conectando" | "ao vivo" | "sem dados novos" | "reconectando";

/**
 * O retrato ao vivo de um projeto e ambiente, atualizado a cada segundo pelo WebSocket.
 *
 * 1. pede um ticket de uso único (REST, com o cookie de sessão);
 * 2. abre o WebSocket com o ticket e assina o projeto e o ambiente;
 * 3. se a conexão cair, reconecta sozinho, esperando 1 s, 2 s, 4 s... (sem martelar a API
 *    que acabou de voltar);
 * 4. se os retratos pararem de chegar, avisa que os dados estão velhos, em vez de mostrar
 *    números congelados como se fossem atuais.
 */
export function useLive(projectId: number, environment: string | undefined) {
  // Cada valor guarda de qual canal (projeto:ambiente) veio. Ao trocar de ambiente, o que é
  // do canal anterior é ignorado na renderização, sem precisar "zerar" o estado no efeito.
  const channel = `${projectId}:${environment}`;
  const [snapshot, setSnapshot] = useState<{ channel: string; data: LiveSnapshot; at: number } | null>(null);
  const [status, setStatus] = useState<{ channel: string; value: LiveStatus } | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!environment) return;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let closed = false; // a tela saiu: não reconectar

    async function connect() {
      try {
        const { ticket } = await api.liveTicket();
        if (closed) return;
        const url = `${API_URL.replace(/^http/, "ws")}/api/live?ticket=${encodeURIComponent(ticket)}`;
        socket = new WebSocket(url);
        socket.onopen = () => {
          attempt = 0;
          socket?.send(JSON.stringify({ type: "subscribe", project_id: projectId, environment }));
        };
        socket.onmessage = (event) => {
          const message = JSON.parse(event.data) as LiveMessage;
          if (message.type === "snapshot") {
            setSnapshot({ channel: key, data: message.data, at: Date.now() });
            setStatus({ channel: key, value: "ao vivo" });
          }
        };
        socket.onclose = () => scheduleReconnect();
      } catch {
        scheduleReconnect(); // a API pode estar fora: tenta de novo daqui a pouco
      }
    }

    function scheduleReconnect() {
      if (closed) return;
      setStatus({ channel: key, value: "reconectando" });
      retry = setTimeout(connect, reconnectDelay(attempt++));
    }

    const key = `${projectId}:${environment}`;
    connect();
    // um relógio de 1 s só para saber se o último retrato ficou velho
    const tick = setInterval(() => setNow(Date.now()), 1_000);

    return () => {
      // limpeza: sair da tela (ou trocar de ambiente) fecha o socket e cancela tudo
      closed = true;
      clearTimeout(retry);
      clearInterval(tick);
      socket?.close();
    };
  }, [projectId, environment]);

  const current = snapshot?.channel === channel ? snapshot : null;
  const currentStatus: LiveStatus = status?.channel === channel ? status.value : "conectando";
  const stale = currentStatus === "ao vivo" && current !== null && now - current.at > STALE_AFTER_MS;
  return {
    snapshot: current?.data ?? null,
    status: stale ? ("sem dados novos" as const) : currentStatus,
    receivedAt: current?.at ?? 0,
  };
}

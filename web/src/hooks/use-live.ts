"use client";

import { useEffect, useState } from "react";

import { API_URL, api } from "@/lib/api";
import { type LiveMessage, type LiveSnapshot, type LiveStatus, liveStatus, reconnectDelay } from "@/lib/live";

export type { LiveStatus } from "@/lib/live";

type Signals = {
  channel: string; // de qual projeto:ambiente vieram
  connection: "conectando" | "assinado" | "reconectando";
  subscribedAt: number | null;
  snapshot: LiveSnapshot | null;
  snapshotAt: number | null;
  idleAt: number | null;
};

/**
 * O retrato ao vivo de um projeto e ambiente, atualizado a cada segundo pelo WebSocket.
 *
 * 1. pede um ticket de uso único (REST, com o cookie de sessão);
 * 2. abre o WebSocket com o ticket e assina o projeto e o ambiente;
 * 3. se a conexão cair, reconecta sozinho, esperando 1 s, 2 s, 4 s... (sem martelar a API
 *    que acabou de voltar);
 * 4. separa "sem tráfego" (chega o aviso idle) de "o processamento parou" (não chega nada),
 *    em vez de mostrar números congelados como se fossem atuais.
 */
export function useLive(projectId: number, environment: string | undefined) {
  // Os sinais guardam de qual canal (projeto:ambiente) vieram. Ao trocar de ambiente, o que é
  // do canal anterior é ignorado na renderização, sem precisar "zerar" o estado no efeito.
  const channel = `${projectId}:${environment}`;
  const [signals, setSignals] = useState<Signals | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!environment) return;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let closed = false; // a tela saiu: não reconectar
    const key = `${projectId}:${environment}`;
    const update = (change: Partial<Signals>) =>
      setSignals((current) => ({
        ...(current?.channel === key
          ? current
          : { channel: key, connection: "conectando", subscribedAt: null, snapshot: null, snapshotAt: null, idleAt: null }),
        ...change,
      }));

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
          const at = Date.now();
          if (message.type === "subscribed") update({ connection: "assinado", subscribedAt: at });
          else if (message.type === "snapshot") update({ snapshot: message.data, snapshotAt: at });
          else if (message.type === "idle") update({ idleAt: at });
        };
        socket.onclose = () => scheduleReconnect();
      } catch {
        scheduleReconnect(); // a API pode estar fora: tenta de novo daqui a pouco
      }
    }

    function scheduleReconnect() {
      if (closed) return;
      update({ connection: "reconectando" });
      retry = setTimeout(connect, reconnectDelay(attempt++));
    }

    connect();
    // um relógio de 1 s só para perceber quando os sinais param de chegar
    const tick = setInterval(() => setNow(Date.now()), 1_000);

    return () => {
      // limpeza: sair da tela (ou trocar de ambiente) fecha o socket e cancela tudo
      closed = true;
      clearTimeout(retry);
      clearInterval(tick);
      socket?.close();
    };
  }, [projectId, environment]);

  const current = signals?.channel === channel ? signals : null;
  const status: LiveStatus = current
    ? liveStatus({ ...current, now: Math.max(now, current.snapshotAt ?? 0, current.idleAt ?? 0) })
    : "conectando";
  return {
    // sem tráfego, o último retrato é de mais de um minuto atrás: não é "o agora"
    snapshot: status === "sem tráfego" ? null : (current?.snapshot ?? null),
    status,
    receivedAt: current?.snapshotAt ?? 0,
  };
}

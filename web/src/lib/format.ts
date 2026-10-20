/** Como números e horários aparecem na tela. Funções puras, testadas em format.test.ts. */

const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

/** 0,4 ms · 87 ms · 1,2 s · 2 min 5 s */
export function formatDuration(ms: number): string {
  if (ms < 1) return `${decimal.format(ms)} ms`;
  if (ms < 1000) return `${integer.format(ms)} ms`;
  if (ms < 60_000) return `${decimal.format(ms / 1000)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds ? `${minutes} min ${seconds} s` : `${minutes} min`;
}

/** 14:03:21.120, no fuso de quem está olhando */
export function formatClock(iso: string): string {
  const d = new Date(iso);
  const hms = d.toLocaleTimeString("pt-BR", { hour12: false });
  return `${hms}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

/** "agora", "há 12 s", "há 3 min", "há 2 h", ou a data */
export function formatAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 5) return "agora";
  if (seconds < 60) return `há ${seconds} s`;
  if (seconds < 3600) return `há ${Math.floor(seconds / 60)} min`;
  if (seconds < 86_400) return `há ${Math.floor(seconds / 3600)} h`;
  return new Date(iso).toLocaleDateString("pt-BR");
}

/** Os primeiros caracteres de um id, para caber na tabela: 5b8efff7… */
export function shortId(id: string, size = 8): string {
  return id.length > size ? `${id.slice(0, size)}…` : id;
}

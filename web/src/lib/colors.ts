/**
 * Cada serviço ganha uma cor, sempre a mesma: o "orders" é azul em toda tela, em todo
 * trace e em todo dia, porque a cor sai do nome (um hash), e não da ordem em que apareceu.
 */

// Cores distinguíveis entre si e legíveis sobre o fundo escuro do TraceFlow.
const PALETTE = [
  "#3b82f6", // azul
  "#22c55e", // verde
  "#f59e0b", // âmbar
  "#a78bfa", // violeta
  "#22d3ee", // ciano
  "#f472b6", // rosa
  "#fb923c", // laranja
  "#34d399", // esmeralda
  "#e879f9", // fúcsia
  "#facc15", // amarelo
];

/** FNV-1a: um hash simples e rápido, com boa distribuição para textos curtos. */
export function hashName(name: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < name.length; i++) {
    hash ^= name.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

export function serviceColor(name: string): string {
  return PALETTE[hashName(name) % PALETTE.length];
}

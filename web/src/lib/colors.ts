/**
 * Cada serviço ganha uma cor, sempre a mesma: o "orders" é azul em toda tela, em todo
 * trace e em todo dia, porque a cor sai do nome (um hash), e não da ordem em que apareceu.
 */

// Seis cores de categoria para fundo escuro, validadas com o script de paleta (não "no olho"):
// faixa de luminosidade, saturação mínima, separação para daltonismo (ΔE ≥ 8 entre vizinhas),
// separação para visão normal (ΔE ≥ 15) e contraste ≥ 3:1 sobre #0b1020 e #111831.
// Verde e vermelho ficam de fora de propósito: no TraceFlow eles são cores de ESTADO
// (saudável, erro) e nunca podem significar "um serviço qualquer".
// Com mais de seis serviços as cores se repetem; por isso a cor nunca está sozinha: o nome
// do serviço aparece sempre ao lado (o texto em cor neutra, a cor num ponto ou na barra).
export const PALETTE = [
  "#3987e5", // azul
  "#d95926", // laranja
  "#199e70", // água
  "#c98500", // amarelo
  "#d55181", // magenta
  "#9085e9", // violeta
];

// p50, p95 e p99 são uma ORDEM (do mais rápido ao mais lento): uma rampa de um só tom
export const PERCENTILE_COLORS = { p50: "#9cc1f5", p95: "#3987e5", p99: "#1f5fb8" };

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

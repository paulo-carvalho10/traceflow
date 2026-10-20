/**
 * A matemática do waterfall: onde cada barra começa, quanto ocupa e onde ficam as marcas
 * da régua de tempo. Puro (sem React), testado em waterfall.test.ts.
 */

/** Largura mínima de uma barra, em %, para um span de 0,1 ms num trace de 2 s não sumir. */
export const MIN_BAR_PERCENT = 0.4;

export type Bar = { left: number; width: number };

/** Posição da barra, em % da largura da linha do tempo. */
export function barPosition(offsetMs: number, durationMs: number, totalMs: number): Bar {
  if (totalMs <= 0) return { left: 0, width: 100 };
  const left = clamp((offsetMs / totalMs) * 100, 0, 100);
  const width = clamp((durationMs / totalMs) * 100, MIN_BAR_PERCENT, 100 - left);
  return { left, width: Math.max(width, Math.min(MIN_BAR_PERCENT, 100 - left)) };
}

/**
 * Marcas "redondas" para a régua: passos de 1, 2 ou 5 × 10ⁿ, como num paquímetro.
 * Um trace de 420 ms ganha marcas a cada 100 ms (0, 100, 200, 300, 400), não a cada 84.
 */
export function ticks(totalMs: number, target = 5): number[] {
  if (totalMs <= 0) return [0];
  const rough = totalMs / target;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? 10 * magnitude;
  const marks: number[] = [];
  for (let t = 0; t <= totalMs + 1e-9; t += step) marks.push(Math.round(t * 1e6) / 1e6);
  return marks;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

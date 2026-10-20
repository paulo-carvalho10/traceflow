/**
 * As marcas dos eixos. O Recharts, sozinho, põe a última marca no maior valor do dado
 * ("161 ms") e divide o resto em passos quebrados ("1,5%", 11 em 11 segundos). Quem lê o
 * gráfico usa as marcas como régua: elas precisam cair em números redondos.
 */

const NICE = [1, 2, 2.5, 5, 10];

/** O menor passo "redondo" (1, 2, 2,5 ou 5 vezes uma potência de 10) que seja >= raw. */
export function niceStep(raw: number): number {
  if (!(raw > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const factor = NICE.find((n) => n * power >= raw * (1 - 1e-9)) ?? 10;
  return factor * power;
}

/**
 * As marcas do eixo Y, de zero até um topo redondo que cubra o maior valor (no máximo 5
 * divisões). Ex.: 161 → 0, 50, 100, 150, 200; 0,05 → 0, 2%, 4%, 6%.
 */
export function valueTicks(max: number, divisions = 4): number[] {
  if (!(max > 0)) return [0, 1]; // tudo zero: um eixo mínimo, com o zero embaixo
  const step = niceStep(max / divisions);
  const count = Math.ceil(max / step - 1e-9);
  // toPrecision corta o lixo do ponto flutuante (3 × 0,02 = 0,06000000000000001)
  return Array.from({ length: count + 1 }, (_, i) => Number((i * step).toPrecision(12)));
}

const SECOND = 1_000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const TIME_STEPS = [
  5 * SECOND, 10 * SECOND, 15 * SECOND, 30 * SECOND,
  MINUTE, 2 * MINUTE, 5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE,
  HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, 24 * HOUR,
];

/**
 * As marcas do eixo do tempo em horários redondos (18:29:30, 18:29:45...), no fuso de quem
 * olha: o alinhamento desconta o fuso, senão as marcas de 6 h cairiam em 03:00 e 09:00 aqui
 * no Brasil (alinhadas à meia-noite de Greenwich).
 */
export function timeTicks(start: number, end: number, maxTicks = 5): number[] {
  if (!(end > start)) return [start];
  const step = TIME_STEPS.find((s) => (end - start) / s <= maxTicks) ?? 24 * HOUR;
  const offset = new Date(start).getTimezoneOffset() * MINUTE;
  let t = Math.ceil((start - offset) / step) * step + offset;
  const ticks: number[] = [];
  for (; t <= end; t += step) ticks.push(t);
  return ticks;
}

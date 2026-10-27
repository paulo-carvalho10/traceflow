/**
 * As cores dos dados. No TraceFlow, cor comunica ESTADO (saudável, alerta, crítico), e os
 * serviços não têm cor própria: o nome identifica o serviço, e o ponto ao lado diz a saúde.
 *
 * Uma paleta de serviços foi testada com o validador de paletas e não coube: as cores de
 * estado e o destaque já ocupam o verde, o âmbar, o vermelho e os azuis, e todo laranja,
 * ciano ou magenta ficava perto demais de um estado (ΔE abaixo de 15). Uma cor de serviço
 * parecida com a de erro faria alguém ler "falha" onde não há.
 */

// p50, p95 e p99 são uma ORDEM (do mais rápido ao mais lento): uma rampa no tom do destaque,
// do claro ao escuro, validada (um tom só, luminosidade em ordem, passos visíveis)
export const PERCENTILE_COLORS = { p50: "#b4c4f4", p95: "#6687e8", p99: "#3d5dc0" };

export const STATE_COLORS = {
  healthy: "var(--success)",
  degraded: "var(--warning)",
  failing: "var(--destructive)",
  unresponsive: "var(--destructive)",
  idle: "var(--faint)",
} as const;

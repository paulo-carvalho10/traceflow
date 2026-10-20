import { cn } from "@/lib/utils";

/**
 * A tendência numa linha só, sem eixos: o desenho inteiro em cinza (contexto) e o ponto
 * atual na cor principal. SVG puro: centenas delas numa tabela não pesam como gráficos completos.
 */
export function Sparkline({ values, className }: { values: number[]; className?: string }) {
  if (values.length < 2) return null;
  const width = 112;
  const height = 32;
  const pad = 4;
  const max = Math.max(...values, 1e-9);
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - pad * 2);
  const y = (v: number) => height - pad - (v / max) * (height - pad * 2);
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = values.length - 1;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={cn("overflow-visible", className)} aria-hidden>
      <polyline
        points={points}
        fill="none"
        stroke="var(--muted-foreground)"
        strokeOpacity={0.6}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* o ponto atual: cor principal, com um anel da cor do fundo para descolar da linha */}
      <circle cx={x(last)} cy={y(values[last])} r={3} fill="var(--primary)" stroke="var(--card)" strokeWidth={2} />
    </svg>
  );
}

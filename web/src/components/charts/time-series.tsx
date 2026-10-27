"use client";

import { Table2 } from "lucide-react";
import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button } from "@/components/ui/button";
import { timeTicks, valueTicks } from "@/lib/ticks";
import { cn } from "@/lib/utils";

export type Series = { key: string; label: string; color: string };
export type Row = { t: number } & Record<string, number | null>;

/**
 * Um gráfico de linha no tempo, com as regras de visualização do projeto:
 * - linhas finas (1,5 px); com uma série só, uma área a 8% de opacidade por baixo;
 * - um limite opcional (ex.: "erro ≥ 5%"), em linha âmbar fina e com texto;
 * - grade horizontal em linha fina e discreta (nunca tracejada), um eixo Y só;
 * - cursor vertical que acha o horário e uma dica com TODAS as séries (o valor em destaque);
 * - com 2 ou mais séries, legenda acima e o nome no fim de cada linha;
 * - um botão para ver os mesmos números como tabela (a dica nunca é o único caminho).
 */
export function TimeSeries({
  title,
  data,
  series,
  format,
  height = 200,
  minMax,
  dimmed = false,
  bare = false,
  threshold,
}: {
  title: string;
  data: Row[];
  series: Series[];
  format: (value: number) => string;
  height?: number;
  minMax?: number; // o topo mínimo do eixo Y (ex.: 5% na taxa de erro, para zero não virar uma escala inventada)
  dimmed?: boolean; // recarregando: mantém o desenho anterior, mais apagado, sem "piscar"
  bare?: boolean; // dentro de um painel: sem a moldura própria
  threshold?: { value: number; label: string };
}) {
  const [asTable, setAsTable] = useState(false);
  const single = series.length === 1;
  // O formato da hora segue o período mostrado: segundos para o último minuto, horas e
  // minutos para um dia, e a data só quando o período passa de um dia
  const span = data.length > 1 ? data[data.length - 1].t - data[0].t : 0;
  const formatTime = (t: number) =>
    new Date(t).toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
      second: span <= 10 * 60_000 ? "2-digit" : undefined,
      day: span > 24 * 3_600_000 ? "2-digit" : undefined,
      month: span > 24 * 3_600_000 ? "2-digit" : undefined,
    });
  const tick = (v: number) => format(v).replace(/ /g, "\u00a0"); // espaço que não quebra: "600 ms" numa linha só
  const yTicks = valueTicks(Math.max(dataMax(data, series), minMax ?? 0, threshold ? threshold.value * 1.2 : 0));
  const xTicks = data.length ? timeTicks(data[0].t, data[data.length - 1].t) : [];
  const last = data.length - 1;
  const endLabels = !single && !labelsCollide(data, series, height);

  return (
    <figure className={cn(bare ? "px-3 pt-2.5 pb-2" : "rounded-lg border bg-card px-3 pt-2.5 pb-2")}>
      <figcaption className="mb-2 flex items-center justify-between gap-3">
        <span className="text-[13px] font-medium">{title}</span>
        <span className="flex items-center gap-3">
          {!single &&
            series.map((s) => (
              <span key={s.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className="h-0.5 w-3 rounded-full" style={{ background: s.color }} />
                {s.label}
              </span>
            ))}
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={() => setAsTable((v) => !v)}
            aria-label={asTable ? "Ver como gráfico" : "Ver como tabela"}
            aria-pressed={asTable}
          >
            <Table2 className="size-3.5" />
          </Button>
        </span>
      </figcaption>

      {asTable ? (
        <div className="max-h-[220px] overflow-y-auto text-xs">
          <table className="w-full">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-normal">Horário</th>
                {series.map((s) => (
                  <th key={s.key} className="py-1 text-right font-normal">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-mono tabular">
              {[...data].reverse().map((row) => (
                <tr key={row.t} className="border-t border-border/50">
                  <td className="py-1">{formatTime(row.t)}</td>
                  {series.map((s) => (
                    <td key={s.key} className="py-1 text-right">
                      {row[s.key] === null || row[s.key] === undefined ? "–" : format(row[s.key] as number)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={cn("transition-opacity", dimmed && "opacity-50")} style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 6, right: single ? 8 : 36, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" strokeWidth={1} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                ticks={xTicks}
                tickFormatter={formatTime}
                tick={{ fill: "var(--faint)", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "var(--border)" }}
              />
              <YAxis
                tickFormatter={tick}
                domain={[0, yTicks[yTicks.length - 1]]}
                ticks={yTicks}
                tick={{ fill: "var(--faint)", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={56}
              />
              <Tooltip
                cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
                isAnimationActive={false}
                content={({ active, payload, label }) =>
                  active && payload?.length ? (
                    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-lg">
                      <div className="mb-1 font-mono text-[11px] text-muted-foreground">{formatTime(Number(label))}</div>
                      {series.map((s) => {
                        const item = payload.find((p) => p.dataKey === s.key);
                        const value = item?.value as number | null | undefined;
                        return (
                          <div key={s.key} className="flex items-center gap-2">
                            <span className="h-0.5 w-3 rounded-full" style={{ background: s.color }} />
                            <span className="font-mono font-semibold text-foreground tabular">
                              {value === null || value === undefined ? "–" : format(value)}
                            </span>
                            <span className="text-muted-foreground">{s.label}</span>
                          </div>
                        );
                      })}
                    </div>
                  ) : null
                }
              />
              {single && (
                <Area
                  dataKey={series[0].key}
                  type="monotone"
                  stroke="none"
                  fill={series[0].color}
                  fillOpacity={0.08}
                  isAnimationActive={false}
                  connectNulls
                />
              )}
              {threshold && (
                <ReferenceLine
                  y={threshold.value}
                  stroke="var(--warning)"
                  strokeOpacity={0.6}
                  strokeWidth={1}
                  ifOverflow="extendDomain"
                  label={{ value: threshold.label, position: "insideTopRight", fill: "var(--warning)", fontSize: 10 }}
                />
              )}
              {series.map((s) => (
                <Line
                  key={s.key}
                  dataKey={s.key}
                  type="monotone"
                  stroke={s.color}
                  strokeWidth={1.5}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  dot={
                    !endLabels
                      ? false
                      : (props: { index?: number; cx?: number; cy?: number }) =>
                          // o nome no fim da linha, em cor de texto (a cor fica na linha)
                          props.index === last && props.cx !== undefined && props.cy !== undefined ? (
                            <text
                              key={`fim-${s.key}`}
                              x={props.cx + 6}
                              y={props.cy}
                              dy={4}
                              fontSize={11}
                              fill="var(--muted-foreground)"
                            >
                              {s.label}
                            </text>
                          ) : (
                            <g key={`p-${s.key}-${props.index}`} />
                          )
                  }
                  activeDot={{ r: 3.5, stroke: "var(--card)", strokeWidth: 2 }}
                  isAnimationActive={false} // dado ao vivo: animar a cada segundo distrai
                  connectNulls
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}

/**
 * Os nomes no fim das linhas só aparecem se não ficarem colados: quando as linhas terminam
 * perto umas das outras, empilhar os rótulos os separa das linhas e vira ruído. Aí ficam a
 * legenda (acima) e a dica do cursor.
 */
export function labelsCollide(data: Row[], series: Series[], height: number, minGapPx = 14): boolean {
  if (data.length === 0) return true;
  const lastRow = data[data.length - 1];
  const ends = series
    .map((s) => lastRow[s.key])
    .filter((v): v is number => typeof v === "number")
    .sort((a, b) => a - b);
  if (ends.length < series.length) return true; // alguma linha não chega ao fim: sem rótulo
  const ticks = valueTicks(dataMax(data, series)); // a escala é a do eixo, que vai até um topo redondo
  const pxPerUnit = (height - 30) / ticks[ticks.length - 1]; // a altura útil, descontando o eixo do tempo
  return ends.some((v, i) => i > 0 && (v - ends[i - 1]) * pxPerUnit < minGapPx);
}

function dataMax(data: Row[], series: Series[]): number {
  return Math.max(0, ...data.flatMap((row) => series.map((s) => row[s.key] ?? 0)));
}

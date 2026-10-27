import { TriangleAlert } from "lucide-react";

import { Sparkline } from "@/components/charts/sparkline";
import { cn } from "@/lib/utils";

/**
 * Um número em destaque: rótulo, valor e, se houver, a tendência do último minuto.
 * O valor usa algarismos proporcionais (tabular-nums deixaria "121" frouxo em tamanho grande).
 * Um alerta, quando existe, vem com ícone e texto: estado nunca é só cor.
 */
export function StatTile({
  label,
  value,
  hint,
  trend,
  alert,
  className,
}: {
  label: string;
  value: string;
  hint?: string;
  trend?: number[];
  alert?: string;
  className?: string;
}) {
  return (
    <div className={cn("rounded-lg border bg-card p-4", className)}>
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-end justify-between gap-3">
        <div className="text-3xl font-semibold tracking-tight">{value}</div>
        {trend && trend.length > 1 && <Sparkline values={trend} className="h-8 w-28" />}
      </div>
      <div className="mt-1 flex min-h-5 items-center gap-1.5 text-xs text-muted-foreground">
        {alert ? (
          <span className="flex items-center gap-1 text-warning">
            <TriangleAlert className="size-3.5" /> {alert}
          </span>
        ) : (
          hint
        )}
      </div>
    </div>
  );
}

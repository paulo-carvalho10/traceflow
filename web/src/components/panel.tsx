import { cn } from "@/lib/utils";

/**
 * Uma área de trabalho com título: borda fina, cabeçalho baixo, conteúdo sem moldura extra.
 * É a unidade das telas (no lugar de cartões grandes e arredondados).
 */
export function Panel({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
  ...rest
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
} & Omit<React.HTMLAttributes<HTMLElement>, "title">) {
  return (
    <section className={cn("min-w-0 rounded-lg border bg-card", className)} {...rest}>
      {(title || actions) && (
        <header className="flex min-h-10 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b px-3 py-2">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-medium">{title}</h2>}
            {description && <p className="text-xs text-muted-foreground">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

/** Uma faixa de números lado a lado, divididos por linhas finas (no lugar de vários cartões). */
export function MetricStrip({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <dl
      className={cn(
        "grid grid-cols-2 overflow-hidden rounded-lg border bg-card sm:grid-cols-3 xl:grid-cols-5 [&>div]:border-b [&>div]:border-r",
        className,
      )}
    >
      {children}
    </dl>
  );
}

export function Metric({
  label,
  value,
  detail,
  tone,
  children,
}: {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  tone?: "warning" | "critical";
  children?: React.ReactNode; // um sparkline, por exemplo
}) {
  return (
    <div className="-mr-px -mb-px min-w-0 px-3 py-2.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 flex items-end justify-between gap-2">
        <span
          className={cn(
            "font-mono text-xl leading-7 tabular",
            tone === "warning" && "text-warning",
            tone === "critical" && "text-destructive",
          )}
        >
          {value}
        </span>
        {children}
      </dd>
      {detail && <dd className="mt-0.5 truncate font-mono text-[11px] text-faint">{detail}</dd>}
    </div>
  );
}

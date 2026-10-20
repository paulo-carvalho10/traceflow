import { cn } from "@/lib/utils";

/** O logotipo: três barras de um waterfall formando um "fluxo", e o nome. */
export function Logo({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
        <rect x="2" y="4" width="14" height="4" rx="2" fill="#3b82f6" />
        <rect x="6" y="10" width="12" height="4" rx="2" fill="#60a5fa" />
        <rect x="10" y="16" width="12" height="4" rx="2" fill="#22c55e" />
      </svg>
      {!compact && <span>TraceFlow</span>}
    </span>
  );
}

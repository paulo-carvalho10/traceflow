import { OctagonAlert } from "lucide-react";
import Link from "next/link";

import { DemoButton } from "@/components/demo-button";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";

// Página pública: componente de servidor. O HTML chega pronto ao navegador (rápido, e o
// Google lê); só o botão da demonstração, que precisa de clique, roda no navegador.

const FEATURES = [
  ["Visão geral ao vivo", "Requisições, erros e latência p50, p95 e p99 de cada serviço, a cada segundo, por WebSocket."],
  ["Traces e waterfall", "O caminho de cada requisição pelos serviços, separando o tempo trabalhando do tempo esperando."],
  ["Mapa de serviços", "Quem chama quem, montado sozinho pelo pareamento das chamadas, inclusive sistemas externos."],
  ["Incidentes", "Abertos sozinhos por regras, com a causa provável, quem sente o impacto e a severidade."],
  ["Incident Playground", "Uma loja de microsserviços para quebrar de propósito e ver o ciclo inteiro do incidente."],
  ["OpenTelemetry", "Qualquer aplicação instrumentada, em qualquer linguagem, manda spans sem mudar uma linha."],
];

// Um trace de compra que falhou no banco externo, desenhado como no produto
const HERO_SPANS: { service: string; op: string; left: number; width: number; depth: number; kind: "work" | "wait" | "fail" }[] = [
  { service: "gateway", op: "POST /checkout", left: 0, width: 100, depth: 0, kind: "work" },
  { service: "orders", op: "POST /orders", left: 2, width: 96, depth: 1, kind: "work" },
  { service: "orders", op: "→ inventory:8000", left: 4, width: 9, depth: 2, kind: "wait" },
  { service: "orders", op: "→ payments:8000", left: 15, width: 80, depth: 2, kind: "wait" },
  { service: "payments", op: "POST /charge", left: 16, width: 78, depth: 3, kind: "fail" },
  { service: "payments", op: "→ bank:8000", left: 18, width: 75, depth: 4, kind: "fail" },
];

const BAR = {
  work: "bg-[color-mix(in_srgb,var(--primary)_72%,var(--card))]",
  wait: "border border-[#5a5d66] bg-[repeating-linear-gradient(135deg,#5a5d66_0_3px,transparent_3px_6px)]",
  fail: "bg-destructive",
};

export default function Home() {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Logo />
        <nav className="flex items-center gap-1">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/login">Entrar</Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/cadastro">Criar conta</Link>
          </Button>
        </nav>
      </header>

      <section className="mx-auto grid max-w-6xl items-center gap-12 px-6 pt-14 pb-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <div>
          <h1 className="text-[34px] leading-[1.15] font-semibold tracking-tight text-balance sm:text-[40px]">
            Veja onde cada requisição gasta o tempo, e o que quebrou primeiro.
          </h1>
          <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-muted-foreground text-pretty">
            O TraceFlow recebe traces das suas APIs e microsserviços pelo OpenTelemetry, mostra o desempenho de cada
            serviço ao vivo e, quando uma falha se espalha, abre um incidente com a causa provável.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-2">
            <DemoButton />
            <Button size="lg" variant="outline" asChild>
              <Link href="/cadastro">Criar conta</Link>
            </Button>
          </div>
          <p className="mt-3 text-xs text-faint">A demonstração abre sem cadastro, com uma loja de verdade gerando tráfego.</p>
        </div>

        <figure className="overflow-hidden rounded-lg border bg-card" aria-label="Um trace com erro e o incidente que ele abriu">
          <div className="flex items-center justify-between border-b px-3 py-2 font-mono text-[11px] text-muted-foreground">
            <span>
              <span className="text-foreground">POST /checkout</span> · 5b8efff7…
            </span>
            <span className="tabular">
              1,24 s · 10 spans · <span className="text-destructive">2 com erro</span>
            </span>
          </div>
          <div className="py-1">
            {HERO_SPANS.map((s, i) => (
              <div key={i} className="grid h-7 grid-cols-[minmax(0,44%)_1fr] items-center gap-3 px-3 font-mono text-[11px]">
                <span className="flex min-w-0 items-center gap-1.5 truncate" style={{ paddingLeft: s.depth * 12 }}>
                  <span className={s.kind === "fail" ? "text-destructive" : "text-muted-foreground"}>{s.service}</span>
                  <span className="truncate text-foreground">{s.op}</span>
                </span>
                <span className="relative h-3">
                  <span className={`absolute inset-y-0 rounded-sm ${BAR[s.kind]}`} style={{ left: `${s.left}%`, width: `${s.width}%` }} />
                </span>
              </div>
            ))}
          </div>
          <figcaption className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t px-3 py-2 text-xs">
            <span className="inline-flex items-center gap-1 rounded-sm border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 text-destructive">
              <OctagonAlert className="size-3.5" /> SEV1 · crítico
            </span>
            <span>bank:8000 falhando</span>
            <span className="font-mono text-faint">causa provável: bank:8000 (externo) · afeta POST /checkout</span>
          </figcaption>
        </figure>
      </section>

      <section className="mx-auto max-w-6xl px-6 pb-20">
        <dl className="grid overflow-hidden rounded-lg border sm:grid-cols-2 lg:grid-cols-3 [&>div]:border-b [&>div]:border-r">
          {FEATURES.map(([title, text]) => (
            <div key={title} className="-mr-px -mb-px px-5 py-4">
              <dt className="text-[13px] font-medium">{title}</dt>
              <dd className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{text}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

import { FlaskConical, Gauge, Network, Radio, Siren, Waypoints } from "lucide-react";
import Link from "next/link";

import { DemoButton } from "@/components/demo-button";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";

// Página pública: componente de servidor. O HTML chega pronto ao navegador (rápido, e o
// Google lê); só o botão da demonstração, que precisa de clique, roda no navegador.

const FEATURES = [
  {
    icon: Gauge,
    title: "Dashboard em tempo real",
    text: "Requisições por segundo, erros, disponibilidade e latência em p50, p95 e p99, atualizados a cada segundo.",
  },
  {
    icon: Waypoints,
    title: "Distributed tracing",
    text: "O caminho de cada requisição por todos os serviços, com o tempo gasto em cada etapa.",
  },
  {
    icon: Network,
    title: "Mapa de dependências",
    text: "Quem chama quem, desenhado sozinho a partir dos próprios traces, sem configuração.",
  },
  {
    icon: Siren,
    title: "Gestão de incidentes",
    text: "Regras configuráveis, causa provável, raio de impacto e severidade pelo efeito em quem usa.",
  },
  {
    icon: FlaskConical,
    title: "Incident Playground",
    text: "Injete uma falha numa loja de microsserviços e acompanhe ela se espalhar, ser detectada e se recuperar.",
  },
  {
    icon: Radio,
    title: "Padrão OpenTelemetry",
    text: "Qualquer aplicação já instrumentada, em qualquer linguagem, manda dados sem mudar uma linha.",
  },
];

// Um trace de compra, desenhado como no produto (a figura do topo)
const HERO_SPANS = [
  { name: "gateway  POST /checkout", left: 0, width: 100, color: "#3b82f6", depth: 0 },
  { name: "orders  POST /orders", left: 3, width: 95, color: "#a78bfa", depth: 1 },
  { name: "inventory  POST /reserve", left: 6, width: 13, color: "#22c55e", depth: 2 },
  { name: "payments  POST /charge", left: 22, width: 68, color: "#f59e0b", depth: 2 },
  { name: "bank  (externo)", left: 24, width: 64, color: "#f59e0b", depth: 3, faded: true },
  { name: "notifications  POST /send", left: 92, width: 5, color: "#22d3ee", depth: 2 },
];

export default function Home() {
  return (
    <div className="relative min-h-screen overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[520px] bg-[radial-gradient(60%_60%_at_50%_0%,rgba(59,130,246,0.18),transparent)]"
      />
      <header className="relative mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Logo />
        <nav className="flex items-center gap-2">
          <Button variant="ghost" asChild>
            <Link href="/login">Entrar</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/cadastro">Criar conta</Link>
          </Button>
        </nav>
      </header>

      <section className="relative mx-auto grid max-w-6xl items-center gap-12 px-6 pt-16 pb-20 lg:grid-cols-2">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
            Understand your systems. Detect issues faster.
          </p>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            Veja onde cada requisição gasta o tempo, e o que quebrou primeiro.
          </h1>
          <p className="mt-5 max-w-xl text-lg text-muted-foreground text-pretty">
            O TraceFlow recebe traces das suas APIs e microsserviços, mostra o desempenho de cada serviço ao vivo e
            aponta a causa provável quando uma falha se espalha.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <DemoButton />
            <Button size="lg" variant="outline" asChild>
              <Link href="/cadastro">Criar conta grátis</Link>
            </Button>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">A demonstração não pede cadastro.</p>
        </div>

        <div className="rounded-2xl border bg-card/80 p-5 shadow-2xl shadow-primary/10 backdrop-blur">
          <div className="mb-4 flex items-center justify-between text-xs text-muted-foreground">
            <span className="font-mono">trace 5b8efff7…</span>
            <span className="font-mono tabular">420 ms · 10 spans · 5 serviços</span>
          </div>
          <div className="space-y-2.5">
            {HERO_SPANS.map((s) => (
              <div key={s.name} className="grid grid-cols-[150px_1fr] items-center gap-3 text-xs">
                <span className="truncate font-mono text-muted-foreground" style={{ paddingLeft: s.depth * 10 }}>
                  {s.name}
                </span>
                <div className="relative h-3 rounded bg-muted/60">
                  <div
                    className="absolute inset-y-0 rounded"
                    style={{
                      left: `${s.left}%`,
                      width: `${s.width}%`,
                      background: s.color,
                      opacity: s.faded ? 0.45 : 0.9,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="relative mx-auto max-w-6xl px-6 pb-24">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div key={title} className="rounded-xl border bg-card/60 p-5">
              <Icon className="size-5 text-primary" />
              <h2 className="mt-3 font-medium">{title}</h2>
              <p className="mt-1.5 text-sm text-muted-foreground">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="relative border-t py-6 text-center text-xs text-muted-foreground">
        TraceFlow · projeto de portfólio · backend em Python (FastAPI, asyncio, Redis Streams, TimescaleDB)
      </footer>
    </div>
  );
}

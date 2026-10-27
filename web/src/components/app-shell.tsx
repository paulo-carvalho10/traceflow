"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  ChartLine,
  ChevronRight,
  ChevronsUpDown,
  FlaskConical,
  FolderKanban,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  Settings,
  Siren,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useState } from "react";

import { ConnectionStatus } from "@/components/live-controls";
import { Logo } from "@/components/logo";
import { GlobalSearch } from "@/components/global-search";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { RANGES, type Range, WorkspaceProvider, useWorkspace } from "@/components/workspace";
import { useOpenIncidents } from "@/hooks/use-open-incidents";
import { useSession } from "@/hooks/use-session";
import { api } from "@/lib/api";
import { SEVERITY } from "@/lib/incidents";
import type { Severity } from "@/lib/live";
import { shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ElementType };

const NAV: NavItem[] = [
  { href: "dashboard", label: "Visão geral", icon: LayoutDashboard },
  { href: "services", label: "Serviços", icon: Boxes },
  { href: "traces", label: "Traces", icon: Waypoints },
  { href: "metrics", label: "Métricas", icon: ChartLine },
  { href: "incidents", label: "Incidentes", icon: Siren },
  { href: "map", label: "Mapa de serviços", icon: Network },
  { href: "playground", label: "Playground", icon: FlaskConical },
  { href: "settings", label: "Configurações", icon: Settings },
];

const COUNT_STYLE = {
  critical: "bg-destructive/15 text-destructive",
  warning: "bg-warning/15 text-warning",
  neutral: "bg-secondary text-muted-foreground",
} as const;

/**
 * A moldura das telas de um projeto: a barra lateral (o projeto e as seções) e o cabeçalho
 * (onde estou, ambiente, período, busca, conexão e conta). Em telas estreitas, a barra lateral
 * vira um painel, e o cabeçalho fica com o essencial.
 */
export function AppShell({ projectId, children }: { projectId: number; children: React.ReactNode }) {
  return (
    <Suspense>
      <WorkspaceProvider projectId={projectId}>
        <Frame>{children}</Frame>
      </WorkspaceProvider>
    </Suspense>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  const me = useSession();
  const pathname = usePathname();
  const { projectId } = useWorkspace();
  const [menuOpen, setMenuOpen] = useState(false);
  const { incidents, worst } = useOpenIncidents(projectId, { notify: !pathname.endsWith("/playground") });

  if (!me.isSuccess) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Carregando…</div>;
  }

  const sidebar = <Sidebar openIncidents={incidents.length} worst={worst} onNavigate={() => setMenuOpen(false)} />;
  const user = { name: me.data.name, detail: me.data.is_demo_visitor ? "visitante da demonstração" : me.data.email };

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar lg:flex">
        {sidebar}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur sm:px-4">
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon-sm" className="lg:hidden" aria-label="Abrir o menu">
                <Menu className="size-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 gap-0 bg-sidebar p-0">
              <SheetTitle className="sr-only">Menu</SheetTitle>
              <SheetDescription className="sr-only">Seções do projeto, ambiente e período</SheetDescription>
              {sidebar}
              <div className="space-y-2 border-t border-sidebar-border p-3 sm:hidden">
                <ScopeControls />
              </div>
            </SheetContent>
          </Sheet>
          <Breadcrumbs />
          <div className="ml-auto flex items-center gap-2">
            <GlobalSearch />
            <div className="hidden items-center gap-2 sm:flex">
              <ScopeControls />
            </div>
            <ConnectionStatus />
            {incidents.length > 0 && worst && (
              <Link
                href={`/projects/${projectId}/incidents`}
                className={cn(
                  "flex h-7 items-center gap-1 rounded-md px-2 font-mono text-xs lg:hidden",
                  COUNT_STYLE[SEVERITY[worst].tone],
                )}
                aria-label={`${incidents.length} incidente(s) aberto(s), o mais grave ${worst}`}
              >
                <Siren className="size-3.5" /> {incidents.length}
              </Link>
            )}
            <UserMenu user={user} />
          </div>
        </header>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

function Sidebar({
  openIncidents,
  worst,
  onNavigate,
}: {
  openIncidents: number;
  worst: Severity | null | undefined;
  onNavigate: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { projectId, project, scoped } = useWorkspace();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });

  return (
    <div className="flex h-full flex-col">
      <Link href="/projects" className="flex h-12 items-center px-4" onClick={onNavigate}>
        <Logo />
      </Link>

      <DropdownMenu>
        <DropdownMenuTrigger className="mx-2 mb-3 flex items-center gap-2 rounded-md border border-sidebar-border px-2.5 py-1.5 text-left text-[13px] text-foreground hover:bg-sidebar-accent">
          <FolderKanban className="size-3.5 shrink-0 text-faint" />
          {project ? <span className="min-w-0 flex-1 truncate">{project.name}</span> : <Skeleton className="h-4 flex-1" />}
          <ChevronsUpDown className="size-3.5 shrink-0 text-faint" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          <DropdownMenuLabel className="text-xs text-muted-foreground">Projetos</DropdownMenuLabel>
          {projects.data?.map((p) => (
            <DropdownMenuItem
              key={p.id}
              onSelect={() => {
                onNavigate();
                router.push(`/projects/${p.id}/dashboard`);
              }}
            >
              <span className="truncate">{p.name}</span>
              {p.is_demo && (
                <Badge variant="secondary" className="ml-auto font-mono text-[10px]">
                  demo
                </Badge>
              )}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => router.push("/projects")}>Todos os projetos</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <nav className="flex flex-1 flex-col gap-px px-2" aria-label="Seções do projeto">
        {NAV.map((item) => {
          const base = `/projects/${projectId}/${item.href}`;
          const active = pathname === base || pathname.startsWith(`${base}/`);
          const Icon = item.icon;
          const count = item.href === "incidents" && openIncidents > 0 && worst ? openIncidents : 0;
          return (
            <Link
              key={item.href}
              href={scoped(base)}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors duration-100",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
              )}
            >
              <Icon className={cn("size-4", active ? "text-primary" : "text-faint group-hover:text-muted-foreground")} />
              {item.label}
              {count > 0 && worst && (
                <span
                  className={cn("ml-auto rounded px-1.5 font-mono text-[11px] leading-5", COUNT_STYLE[SEVERITY[worst].tone])}
                  title={`${count} aberto(s); o mais grave: ${worst}`}
                >
                  {count}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <p className="px-4 py-3 font-mono text-[11px] text-faint">traceflow · v0.10</p>
    </div>
  );
}

/** Onde estou: projeto › seção › item. O último pedaço é a página atual. */
function Breadcrumbs() {
  const pathname = usePathname();
  const { projectId, project, scoped } = useWorkspace();
  const rest = pathname.replace(`/projects/${projectId}`, "").split("/").filter(Boolean);
  const section = NAV.find((n) => n.href === rest[0]);
  const crumbs: { label: string; href?: string; mono?: boolean }[] = [];
  if (section) crumbs.push({ label: section.label, href: scoped(`/projects/${projectId}/${section.href}`) });
  if (rest.length > 1) {
    const item = decodeURIComponent(rest[1]);
    const labels: Record<string, string> = { keys: "Chaves de ingestão", rules: "Regras de detecção" };
    const isId = /^[0-9a-f-]{16,}$/i.test(item);
    crumbs.push({ label: labels[item] ?? (isId ? shortId(item) : item), mono: isId || rest[0] === "services" });
  }
  return (
    <nav aria-label="Você está em" className="flex min-w-0 items-center gap-1.5 text-[13px]">
      <span className="hidden truncate text-muted-foreground md:inline">{project?.name ?? "…"}</span>
      {crumbs.map((c, i) => (
        <span key={i} className="flex min-w-0 items-center gap-1.5">
          <ChevronRight className={cn("size-3.5 shrink-0 text-faint", i === 0 && "hidden md:block")} />
          {c.href && i < crumbs.length - 1 ? (
            <Link href={c.href} className="truncate text-muted-foreground hover:text-foreground">
              {c.label}
            </Link>
          ) : (
            <span className={cn("truncate", c.mono && "font-mono text-xs")} aria-current="page">
              {c.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}

/** O ambiente e o período, que valem para todas as telas do projeto. */
function ScopeControls() {
  const { environment, environments, setEnvironment, range, setRange } = useWorkspace();
  return (
    <>
      <Select value={environment ?? ""} onValueChange={setEnvironment} disabled={environments.length === 0}>
        <SelectTrigger size="sm" className="h-7 w-full gap-1.5 font-mono text-xs sm:w-auto" aria-label="Ambiente">
          <span className="font-sans text-faint">env</span>
          <SelectValue placeholder="nenhum" />
        </SelectTrigger>
        <SelectContent>
          {environments.map((env) => (
            <SelectItem key={env.name} value={env.name} className="font-mono text-xs">
              {env.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={range} onValueChange={(v) => setRange(v as Range)}>
        <SelectTrigger size="sm" className="h-7 w-full gap-1.5 text-xs sm:w-auto" aria-label="Período">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(RANGES) as Range[]).map((r) => (
            <SelectItem key={r} value={r} className="text-xs">
              {RANGES[r].label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </>
  );
}

function UserMenu({ user }: { user: { name: string; detail: string } }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { projectId } = useWorkspace();

  async function logout() {
    await api.logout();
    queryClient.clear(); // nada da sessão anterior pode sobrar no cache
    router.replace("/login");
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="grid size-7 place-items-center rounded-md bg-secondary text-xs font-medium text-foreground hover:bg-accent"
        aria-label={`Conta: ${user.name}`}
      >
        {user.name.slice(0, 1).toUpperCase()}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate text-sm">{user.name}</span>
          <span className="block truncate text-xs text-muted-foreground">{user.detail}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push(`/projects/${projectId}/settings`)}>
          <Settings className="size-4" /> Configurações
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => router.push("/projects")}>
          <FolderKanban className="size-4" /> Todos os projetos
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={logout}>
          <LogOut className="size-4" /> Sair
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** O título da página: discreto, sem ícone. A localização já está no cabeçalho (o breadcrumb). */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3 px-4 pt-5 pb-4 sm:px-6">
      <div className="min-w-0">
        <h1 className="text-[22px] leading-tight font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

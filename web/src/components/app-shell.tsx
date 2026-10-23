"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ChevronsUpDown,
  FlaskConical,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  Siren,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/logo";
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
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useOpenIncidents } from "@/hooks/use-open-incidents";
import { useSession } from "@/hooks/use-session";
import { type Project, api } from "@/lib/api";
import { SEVERITY } from "@/lib/incidents";
import type { Severity } from "@/lib/live";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ElementType; soon?: string; ownerOnly?: boolean };

// As telas que ainda não existem aparecem com a etapa em que chegam: o produto mostra o caminho.
const NAV: NavItem[] = [
  { href: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "traces", label: "Traces", icon: Waypoints },
  { href: "map", label: "Mapa de serviços", icon: Network },
  { href: "incidents", label: "Incidentes", icon: Siren },
  { href: "playground", label: "Playground", icon: FlaskConical },
  { href: "settings/keys", label: "Chaves de ingestão", icon: KeyRound, ownerOnly: true },
];

const COUNT_STYLE = {
  critical: "bg-destructive text-white",
  warning: "bg-warning text-black",
  neutral: "bg-muted-foreground/30 text-foreground",
} as const;

/**
 * A moldura das telas de um projeto. Em telas largas, a barra lateral fica fixa; em telas
 * estreitas (celular, tablet em pé), ela vira um painel que abre pelo botão de menu, e uma
 * barra no topo mostra o essencial, inclusive os incidentes abertos.
 */
export function AppShell({ projectId, children }: { projectId: number; children: React.ReactNode }) {
  const me = useSession();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: me.isSuccess });
  const project = projects.data?.find((p) => p.id === projectId);
  const { incidents, worst } = useOpenIncidents(projectId, { notify: !pathname.endsWith("/playground") });

  if (!me.isSuccess) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Carregando…</div>;
  }

  const sidebar = (
    <SidebarContent
      projectId={projectId}
      project={project}
      projects={projects.data}
      pathname={pathname}
      openIncidents={incidents.length}
      worst={worst}
      user={{ name: me.data.name, detail: me.data.is_demo_visitor ? "visitante da demonstração" : me.data.email }}
      onNavigate={() => setMenuOpen(false)}
    />
  );

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar lg:flex">
        {sidebar}
      </aside>

      {/* a barra do topo, só em telas estreitas */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-sidebar/95 px-3 backdrop-blur lg:hidden">
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Abrir o menu">
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 gap-0 bg-sidebar p-0">
            <SheetTitle className="sr-only">Menu</SheetTitle>
            <SheetDescription className="sr-only">Telas do projeto, troca de projeto e conta</SheetDescription>
            {sidebar}
          </SheetContent>
        </Sheet>
        <Link href="/projects" aria-label="TraceFlow, início">
          <Logo />
        </Link>
        {incidents.length > 0 && worst && (
          <Link
            href={`/projects/${projectId}/incidents`}
            className={cn(
              "ml-auto flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
              COUNT_STYLE[SEVERITY[worst].tone],
            )}
            aria-label={`${incidents.length} incidente(s) aberto(s), o mais grave ${worst}`}
          >
            <Siren className="size-3.5" /> {incidents.length}
          </Link>
        )}
      </header>

      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}

function SidebarContent({
  projectId,
  project,
  projects,
  pathname,
  openIncidents,
  worst,
  user,
  onNavigate,
}: {
  projectId: number;
  project: Project | undefined;
  projects: Project[] | undefined;
  pathname: string;
  openIncidents: number;
  worst: Severity | null | undefined;
  user: { name: string; detail: string };
  onNavigate: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();

  async function logout() {
    await api.logout();
    queryClient.clear(); // nada da sessão anterior pode sobrar no cache
    router.replace("/login");
  }

  return (
    <div className="flex h-full flex-col">
      <Link href="/projects" className="px-4 py-4" onClick={onNavigate}>
        <Logo />
      </Link>

      <DropdownMenu>
        <DropdownMenuTrigger className="mx-3 mb-3 flex items-center justify-between gap-2 rounded-lg border border-sidebar-border px-3 py-2 text-left text-sm hover:bg-sidebar-accent">
          {project ? <span className="truncate">{project.name}</span> : <Skeleton className="h-4 w-32" />}
          <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          <DropdownMenuLabel>Projetos</DropdownMenuLabel>
          {projects?.map((p) => (
            <DropdownMenuItem
              key={p.id}
              onSelect={() => {
                onNavigate();
                router.push(`/projects/${p.id}/dashboard`);
              }}
            >
              <span className="truncate">{p.name}</span>
              {p.is_demo && <Badge variant="secondary" className="ml-auto">demo</Badge>}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => router.push("/projects")}>Todos os projetos</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <nav className="flex flex-1 flex-col gap-0.5 px-3">
        {NAV.filter((item) => !item.ownerOnly || project?.can_edit).map((item) => {
          const href = `/projects/${projectId}/${item.href}`;
          const active = pathname.startsWith(href);
          const Icon = item.icon;
          if (item.soon) {
            return (
              <span
                key={item.href}
                className="flex cursor-default items-center gap-2.5 rounded-lg px-3 py-2 text-sm whitespace-nowrap text-muted-foreground/60"
              >
                <Icon className="size-4" />
                {item.label}
                <span className="ml-auto text-[10px] tracking-wide uppercase">{item.soon}</span>
              </span>
            );
          }
          const count = item.href === "incidents" && openIncidents > 0 && worst ? openIncidents : 0;
          return (
            <Link
              key={item.href}
              href={href}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground hover:bg-sidebar-accent/60",
              )}
            >
              <Icon className={cn("size-4", active && "text-primary")} />
              {item.label}
              {count > 0 && worst && (
                <span
                  className={cn(
                    "ml-auto min-w-5 rounded-full px-1.5 text-center text-[11px] font-semibold",
                    COUNT_STYLE[SEVERITY[worst].tone],
                  )}
                  title={`${count} aberto(s); o mais grave: ${worst}`}
                >
                  {count}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <DropdownMenu>
        <DropdownMenuTrigger className="m-3 flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm hover:bg-sidebar-accent">
          <span className="grid size-7 place-items-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
            {user.name.slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate">{user.name}</span>
            <span className="block truncate text-xs text-muted-foreground">{user.detail}</span>
          </span>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          <DropdownMenuItem onSelect={logout}>
            <LogOut className="size-4" /> Sair
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

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
    <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-5 sm:px-8 sm:py-6">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Activity className="size-5 text-primary" />
          {title}
        </h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

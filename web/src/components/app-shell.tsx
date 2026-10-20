"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ChevronsUpDown,
  FlaskConical,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Network,
  Siren,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Logo } from "@/components/logo";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/hooks/use-session";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ElementType; soon?: string; ownerOnly?: boolean };

// As telas que ainda não existem aparecem com a etapa em que chegam: o produto mostra o caminho.
const NAV: NavItem[] = [
  { href: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "traces", label: "Traces", icon: Waypoints },
  { href: "map", label: "Mapa de serviços", icon: Network, soon: "Etapa 7" },
  { href: "incidents", label: "Incidentes", icon: Siren, soon: "Etapa 8" },
  { href: "playground", label: "Playground", icon: FlaskConical, soon: "Etapa 9" },
  { href: "settings/keys", label: "Chaves de ingestão", icon: KeyRound, ownerOnly: true },
];

/** A moldura das telas de um projeto: barra lateral, troca de projeto e menu da conta. */
export function AppShell({ projectId, children }: { projectId: number; children: React.ReactNode }) {
  const me = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: me.isSuccess });
  const project = projects.data?.find((p) => p.id === projectId);

  async function logout() {
    await api.logout();
    queryClient.clear(); // nada da sessão anterior pode sobrar no cache
    router.replace("/login");
  }

  if (!me.isSuccess) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Carregando…</div>;
  }

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
        <Link href="/projects" className="px-4 py-4">
          <Logo />
        </Link>

        <DropdownMenu>
          <DropdownMenuTrigger className="mx-3 mb-3 flex items-center justify-between gap-2 rounded-lg border border-sidebar-border px-3 py-2 text-left text-sm hover:bg-sidebar-accent">
            {project ? (
              <span className="truncate">{project.name}</span>
            ) : (
              <Skeleton className="h-4 w-32" />
            )}
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuLabel>Projetos</DropdownMenuLabel>
            {projects.data?.map((p) => (
              <DropdownMenuItem key={p.id} onSelect={() => router.push(`/projects/${p.id}/dashboard`)}>
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
                  <span className="ml-auto text-[10px] uppercase tracking-wide">{item.soon}</span>
                </span>
              );
            }
            return (
              <Link
                key={item.href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                )}
              >
                <Icon className={cn("size-4", active && "text-primary")} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <DropdownMenu>
          <DropdownMenuTrigger className="m-3 flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm hover:bg-sidebar-accent">
            <span className="grid size-7 place-items-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
              {me.data.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate">{me.data.name}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {me.data.is_demo_visitor ? "visitante da demonstração" : me.data.email}
              </span>
            </span>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuItem onSelect={logout}>
              <LogOut className="size-4" /> Sair
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </aside>

      <main className="min-w-0 flex-1">{children}</main>
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
    <header className="flex items-start justify-between gap-4 border-b px-8 py-6">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Activity className="size-5 text-primary" />
          {title}
        </h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

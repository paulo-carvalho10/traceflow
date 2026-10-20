"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/logo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/hooks/use-session";
import { api } from "@/lib/api";

export default function ProjectsPage() {
  const me = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: me.isSuccess });

  async function logout() {
    await api.logout();
    queryClient.clear();
    router.replace("/login");
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-10 flex items-center justify-between">
        <Logo />
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          {me.data && <span>{me.data.is_demo_visitor ? "Visitante da demonstração" : me.data.email}</span>}
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut className="size-4" /> Sair
          </Button>
        </div>
      </header>

      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projetos</h1>
          <p className="mt-1 text-sm text-muted-foreground">Cada projeto tem as suas chaves, serviços e ambientes.</p>
        </div>
        {me.data && !me.data.is_demo_visitor && <NewProjectDialog />}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {projects.isPending &&
          Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}
        {projects.data?.map((project) => (
          <Link key={project.id} href={`/projects/${project.id}/traces`}>
            <Card className="h-full transition-colors hover:border-primary/60">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span className="truncate">{project.name}</span>
                  {project.is_demo && <Badge variant="secondary">demo</Badge>}
                </CardTitle>
                <CardDescription className="font-mono text-xs">{project.slug}</CardDescription>
                <CardDescription>{project.can_edit ? "Seu projeto" : "Somente leitura"}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

function NewProjectDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const router = useRouter();
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.createProject(name),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] }); // a lista ficou velha: buscar de novo
      setOpen(false);
      router.push(`/projects/${project.id}/settings/keys`); // o próximo passo natural: criar a chave
    },
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <FolderPlus className="size-4" /> Novo projeto
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <DialogHeader>
            <DialogTitle>Novo projeto</DialogTitle>
            <DialogDescription>Depois de criar, gere uma chave de ingestão para a sua aplicação.</DialogDescription>
          </DialogHeader>
          <div className="my-5 space-y-2">
            <Label htmlFor="project-name">Nome</Label>
            <Input id="project-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              Criar projeto
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

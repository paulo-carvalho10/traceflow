"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { StateLabel } from "@/components/incidents/badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, type Rule, type RuleInput, api } from "@/lib/api";
import { describeRule } from "@/lib/incidents";

type Metric = Rule["metric"];
const ALL = "*";

/** As regras de detecção de um projeto: o que conta como "degradado" e "falhando". */
export function RulesView({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });
  const rules = useQuery({ queryKey: ["rules", projectId], queryFn: () => api.rules(projectId) });
  const canEdit = project.data?.can_edit ?? false;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["rules", projectId] });
  const toggle = useMutation({
    mutationFn: (rule: Rule) => api.updateRule(projectId, rule.id, { enabled: !rule.enabled }),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (rule: Rule) => api.deleteRule(projectId, rule.id), onSuccess: refresh });

  return (
    <div className="space-y-6 px-4 py-5 sm:px-8 sm:py-6">
      <div className="max-w-3xl space-y-2 text-sm text-muted-foreground">
        <p>
          A cada segundo, o processador avalia estas regras sobre os números de cada serviço nos últimos 10 s. Um
          serviço só muda de estado depois de 3 segundos seguidos pedindo a mudança, e uma mudança aqui vale em até 10
          s. &quot;Sem resposta&quot; não é regra: é quando as chamadas para um serviço falham e ele não atende nada.
        </p>
      </div>
      {project.data && !canEdit && (
        <p className="flex items-start gap-2 rounded-xl border border-dashed bg-card px-4 py-3 text-sm text-muted-foreground">
          <Lock className="mt-0.5 size-4 shrink-0" />
          As regras da demonstração são compartilhadas por todos os visitantes, então ficam só para leitura. Crie uma
          conta para ter projetos com as suas próprias regras.
        </p>
      )}

      <section className="overflow-x-auto rounded-xl border bg-card">
        {rules.isPending ? (
          <Skeleton className="m-4 h-24" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Regra</TableHead>
                <TableHead>Então o serviço fica</TableHead>
                <TableHead>Situação</TableHead>
                {canEdit && <TableHead className="w-10" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.data?.map((rule) => (
                <TableRow key={rule.id} className={rule.enabled ? "" : "opacity-60"}>
                  <TableCell className="min-w-72 text-sm whitespace-normal">{describeRule(rule)}</TableCell>
                  <TableCell>
                    <StateLabel state={rule.state} />
                  </TableCell>
                  <TableCell>
                    {canEdit ? (
                      <Button variant="outline" size="sm" onClick={() => toggle.mutate(rule)} aria-pressed={rule.enabled}>
                        {rule.enabled ? "Ligada" : "Desligada"}
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">{rule.enabled ? "ligada" : "desligada"}</span>
                    )}
                  </TableCell>
                  {canEdit && (
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Apagar a regra"
                        onClick={() => confirm("Apagar esta regra?") && remove.mutate(rule)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
              {rules.data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="text-sm text-muted-foreground">
                    Nenhuma regra: só &quot;sem resposta&quot; abre incidentes.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </section>

      {canEdit && <NewRule projectId={projectId} onCreated={refresh} />}
    </div>
  );
}

const UNIT: Record<Metric, string> = {
  error_rate: "%",
  availability: "%",
  p95_ms: "ms",
  p99_ms: "ms",
  rps: "req/s",
};

function NewRule({ projectId, onCreated }: { projectId: number; onCreated: () => void }) {
  const services = useQuery({ queryKey: ["services", projectId, undefined], queryFn: () => api.services(projectId) });
  const [target, setTarget] = useState(ALL);
  const [metric, setMetric] = useState<Metric>("error_rate");
  const [relative, setRelative] = useState(false);
  const [operator, setOperator] = useState<">=" | "<=">(">=");
  const [threshold, setThreshold] = useState("10");
  const [minRequests, setMinRequests] = useState("20");
  const [state, setState] = useState<"degraded" | "failing">("degraded");
  const latency = metric === "p95_ms" || metric === "p99_ms";
  const create = useMutation({
    mutationFn: (rule: RuleInput) => api.createRule(projectId, rule),
    onSuccess: onCreated,
  });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const value = Number(threshold.replace(",", "."));
    const percent = metric === "error_rate" || metric === "availability";
    create.mutate({
      target,
      metric,
      operator: relative ? ">=" : operator,
      threshold: percent && !relative ? value / 100 : value, // a tela fala em %, a API em fração
      relative: latency && relative,
      min_requests: Number(minRequests),
      state,
      enabled: true,
    });
  }

  const unit = latency && relative ? "× a linha de base" : UNIT[metric];
  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border bg-card p-4">
      <h2 className="text-sm font-medium">Nova regra</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Serviço">
          <Select value={target} onValueChange={setTarget}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Qualquer serviço</SelectItem>
              {[...new Set(services.data?.map((s) => s.name))].sort().map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Métrica">
          <Select
            value={metric}
            onValueChange={(v) => {
              setMetric(v as Metric);
              if (v !== "p95_ms" && v !== "p99_ms") setRelative(false);
            }}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="error_rate">Taxa de erro</SelectItem>
              <SelectItem value="p95_ms">Latência p95</SelectItem>
              <SelectItem value="p99_ms">Latência p99</SelectItem>
              <SelectItem value="availability">Disponibilidade</SelectItem>
              <SelectItem value="rps">Tráfego</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label={`Limite (${unit})`}>
          <div className="flex gap-2">
            <Select value={relative ? ">=" : operator} onValueChange={(v) => setOperator(v as ">=" | "<=")} disabled={relative}>
              <SelectTrigger className="w-20" aria-label="Condição">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value=">=">≥</SelectItem>
                <SelectItem value="<=">≤</SelectItem>
              </SelectContent>
            </Select>
            <Input value={threshold} onChange={(e) => setThreshold(e.target.value)} inputMode="decimal" required />
          </div>
        </Field>
        <Field label="Então o serviço fica">
          <Select value={state} onValueChange={(v) => setState(v as "degraded" | "failing")}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="degraded">degradado</SelectItem>
              <SelectItem value="failing">falhando</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label="Mínimo de requisições em 10 s">
          <Input value={minRequests} onChange={(e) => setMinRequests(e.target.value)} inputMode="numeric" required />
        </Field>
        {latency && (
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <input type="checkbox" checked={relative} onChange={(e) => setRelative(e.target.checked)} className="size-4" />
            Relativa à linha de base do serviço
          </label>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={create.isPending}>
          <Plus className="size-4" /> Criar regra
        </Button>
        {create.error && (
          <span className="text-sm text-destructive" role="alert">
            {create.error instanceof ApiError ? create.error.message : "Não deu para criar a regra."}
          </span>
        )}
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

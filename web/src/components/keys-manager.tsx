"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Plus } from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type ApiKey, type NewApiKey, api } from "@/lib/api";
import { formatAgo } from "@/lib/format";

const INGEST_URL = process.env.NEXT_PUBLIC_INGEST_URL ?? "http://localhost:4318";

/** As chaves de ingestão de um projeto: criar (a chave inteira aparece uma vez só) e revogar. */
export function KeysManager({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: ["keys", projectId], queryFn: () => api.keys(projectId) });
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<NewApiKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["keys", projectId] });
  const revoke = useMutation({
    mutationFn: (key: ApiKey) => api.revokeKey(projectId, key.id),
    onSuccess: () => {
      setRevoking(null);
      refresh();
    },
  });

  return (
    <div className="space-y-4 px-8 py-6">
      <div className="flex items-center justify-between">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Cada aplicação manda os spans com uma chave. O TraceFlow guarda só um resumo (hash) dela: a chave inteira
          aparece uma única vez, na criação.
        </p>
        <Button onClick={() => setCreating(true)}>
          <Plus className="size-4" /> Nova chave
        </Button>
      </div>

      <div className="rounded-xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Nome</TableHead>
              <TableHead>Chave</TableHead>
              <TableHead>Criada</TableHead>
              <TableHead>Último uso</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {keys.data?.map((key) => (
              <TableRow key={key.id}>
                <TableCell className="font-medium">{key.name}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">tf_{key.prefix}_••••••••</TableCell>
                <TableCell className="text-muted-foreground">{formatAgo(key.created_at)}</TableCell>
                <TableCell className="text-muted-foreground">
                  {key.last_used_at ? formatAgo(key.last_used_at) : "nunca"}
                </TableCell>
                <TableCell className="text-right">
                  {key.revoked_at ? (
                    <Badge variant="secondary">revogada</Badge>
                  ) : (
                    <Button variant="destructive" size="sm" onClick={() => setRevoking(key)}>
                      Revogar
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {keys.isSuccess && keys.data.length === 0 && (
          <div className="px-6 py-14 text-center text-sm text-muted-foreground">
            <KeyRound className="mx-auto mb-3 size-6 text-primary" />
            Nenhuma chave ainda. Crie uma para a sua aplicação começar a mandar traces.
          </div>
        )}
      </div>

      <CreateKeyDialog
        open={creating}
        onOpenChange={setCreating}
        projectId={projectId}
        onCreated={(key) => {
          setCreating(false);
          setCreated(key);
          refresh();
        }}
      />
      <ShowKeyDialog created={created} onClose={() => setCreated(null)} />

      <Dialog open={revoking !== null} onOpenChange={(open) => !open && setRevoking(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revogar a chave “{revoking?.name}”?</DialogTitle>
            <DialogDescription>
              A ingestão para de aceitar esta chave em até 1 minuto. Aplicações usando ela vão parar de mandar dados.
              Não dá para desfazer.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRevoking(null)}>
              Cancelar
            </Button>
            <Button
              variant="destructive"
              disabled={revoke.isPending}
              onClick={() => revoking && revoke.mutate(revoking)}
            >
              Revogar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CreateKeyDialog({
  open,
  onOpenChange,
  projectId,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: number;
  onCreated: (key: NewApiKey) => void;
}) {
  const [name, setName] = useState("");
  const create = useMutation({ mutationFn: () => api.createKey(projectId, name), onSuccess: onCreated });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <DialogHeader>
            <DialogTitle>Nova chave de ingestão</DialogTitle>
            <DialogDescription>Um nome que diga onde ela vai ser usada, como “produção” ou “api-pagamentos”.</DialogDescription>
          </DialogHeader>
          <div className="my-5 space-y-2">
            <Label htmlFor="key-name">Nome</Label>
            <Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              Criar chave
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ShowKeyDialog({ created, onClose }: { created: NewApiKey | null; onClose: () => void }) {
  const env = created
    ? [
        `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${INGEST_URL}/v1/traces`,
        `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20${created.key}`,
        "OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=producao",
      ].join("\n")
    : "";
  return (
    <Dialog open={created !== null} onOpenChange={(open) => !open && onClose()}>
      {/* minmax(0, 1fr): a coluna do grid não cresce com a linha de código mais longa; o bloco rola */}
      <DialogContent className="grid-cols-[minmax(0,1fr)] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Chave criada</DialogTitle>
          <DialogDescription>Copie agora: depois que esta janela fechar, ela não aparece mais.</DialogDescription>
        </DialogHeader>
        <Alert>
          <AlertTitle>Sua chave</AlertTitle>
          <AlertDescription>
            <CopyBlock text={created?.key ?? ""} />
          </AlertDescription>
        </Alert>
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            Na sua aplicação instrumentada com OpenTelemetry, estas variáveis bastam:
          </p>
          <CopyBlock text={env} />
        </div>
        <DialogFooter>
          <Button onClick={onClose}>Já copiei</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative w-full">
      <pre className="overflow-x-auto rounded-lg border bg-background p-3 pr-12 font-mono text-xs leading-relaxed whitespace-pre">
        {text}
      </pre>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="absolute top-2 right-2"
        aria-label="Copiar"
        onClick={async () => {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
      </Button>
    </div>
  );
}

"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Panel } from "@/components/panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useWorkspace } from "@/components/workspace";
import { formatAgo, formatDateTime } from "@/lib/format";

const INGEST_URL = process.env.NEXT_PUBLIC_INGEST_URL ?? "http://localhost:4318";

/** O projeto: identificação, ambientes vistos e como mandar spans para ele. */
export function ProjectSettings() {
  const { project, environments } = useWorkspace();
  const config = [
    `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${INGEST_URL}/v1/traces`,
    "OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<a sua chave>",
    "OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=producao",
  ].join("\n");

  return (
    <div className="grid gap-4 px-4 py-4 pb-8 sm:px-6 xl:grid-cols-2">
      <Panel title="Projeto">
        <dl className="divide-y text-[13px]">
          {[
            ["Nome", project?.name],
            ["Id", project ? <span className="font-mono">{project.id}</span> : null],
            ["Slug", project ? <span className="font-mono">{project.slug}</span> : null],
            ["Criado em", project ? <span className="font-mono">{formatDateTime(project.created_at)}</span> : null],
            ["Seu acesso", project ? (project.can_edit ? "dono: pode criar chaves e editar regras" : "leitura") : null],
          ].map(([label, value]) => (
            <div key={String(label)} className="grid grid-cols-[120px_1fr] gap-3 px-3 py-2">
              <dt className="text-muted-foreground">{label}</dt>
              <dd>{value ?? "…"}</dd>
            </div>
          ))}
        </dl>
      </Panel>

      <Panel title="Ambientes" description="Criados sozinhos pelo atributo deployment.environment.name dos spans">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Ambiente</TableHead>
              <TableHead className="text-right">Serviços</TableHead>
              <TableHead className="text-right">Último span</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {environments.map((env) => (
              <TableRow key={env.name}>
                <TableCell className="font-mono text-xs">{env.name}</TableCell>
                <TableCell className="text-right font-mono text-xs tabular">{env.services}</TableCell>
                <TableCell className="text-right font-mono text-xs text-muted-foreground">{formatAgo(env.last_seen)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {environments.length === 0 && <p className="px-3 py-6 text-[13px] text-muted-foreground">Nenhum span chegou ainda.</p>}
      </Panel>

      <Panel
        title="Mandar spans de uma aplicação"
        description="Qualquer aplicação instrumentada com OpenTelemetry, pelo protocolo OTLP/HTTP"
        className="xl:col-span-2"
        actions={<CopyButton text={config} />}
      >
        <pre className="overflow-x-auto px-3 py-3 font-mono text-xs leading-6 text-muted-foreground">{config}</pre>
        <p className="border-t px-3 py-2 text-xs text-faint">
          A chave sai em Configurações › Chaves de ingestão. O ambiente pode ser qualquer nome (producao, staging...):
          ele aparece no seletor do cabeçalho assim que o primeiro span chegar.
        </p>
      </Panel>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
      {copied ? "copiado" : "copiar"}
    </button>
  );
}

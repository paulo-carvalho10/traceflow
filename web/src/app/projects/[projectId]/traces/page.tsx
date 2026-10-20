import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/app-shell";
import { TraceSearch } from "@/components/traces/trace-search";

export const metadata: Metadata = { title: "Traces" };

export default async function TracesPage({ params }: PageProps<"/projects/[projectId]/traces">) {
  const { projectId } = await params;
  return (
    <>
      <PageHeader
        title="Traces"
        description="Cada linha é uma requisição que entrou pela porta de um serviço. Clique para ver o caminho dela."
      />
      <Suspense>
        <TraceSearch projectId={Number(projectId)} />
      </Suspense>
    </>
  );
}

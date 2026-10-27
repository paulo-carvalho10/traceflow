import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/app-shell";
import { TraceSearch } from "@/components/traces/trace-search";

export const metadata: Metadata = { title: "Traces" };

export default function TracesPage() {
  return (
    <>
      <PageHeader title="Traces" description="Cada linha é uma requisição que entrou por um serviço. Clique para ver o caminho dela." />
      <Suspense>
        <TraceSearch />
      </Suspense>
    </>
  );
}

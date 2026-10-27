import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { MetricsView } from "@/components/metrics/metrics-view";

export const metadata: Metadata = { title: "Métricas" };

export default function MetricsPage() {
  return (
    <>
      <PageHeader title="Métricas" description="Todos os serviços lado a lado, na mesma escala, no período escolhido." />
      <MetricsView />
    </>
  );
}

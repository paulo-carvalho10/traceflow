import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { IncidentsView } from "@/components/incidents/incidents-view";

export const metadata: Metadata = { title: "Incidentes" };

export default async function IncidentsPage({ params }: PageProps<"/projects/[projectId]/incidents">) {
  const { projectId } = await params;
  return (
    <>
      <PageHeader title="Incidentes" description="Detectados sozinhos, com a causa provável, o impacto e a severidade." />
      <IncidentsView projectId={Number(projectId)} />
    </>
  );
}

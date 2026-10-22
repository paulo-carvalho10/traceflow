import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { IncidentDetailView } from "@/components/incidents/incident-detail";

export const metadata: Metadata = { title: "Incidente" };

export default async function IncidentPage({ params }: PageProps<"/projects/[projectId]/incidents/[incidentId]">) {
  const { projectId, incidentId } = await params;
  return (
    <>
      <PageHeader title="Incidente" />
      <IncidentDetailView projectId={Number(projectId)} incidentId={incidentId} />
    </>
  );
}

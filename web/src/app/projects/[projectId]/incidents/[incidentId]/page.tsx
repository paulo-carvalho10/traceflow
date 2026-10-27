import type { Metadata } from "next";

import { IncidentDetailView } from "@/components/incidents/incident-detail";

export const metadata: Metadata = { title: "Incidente" };

export default async function IncidentPage({ params }: PageProps<"/projects/[projectId]/incidents/[incidentId]">) {
  const { projectId, incidentId } = await params;
  return <IncidentDetailView projectId={Number(projectId)} incidentId={incidentId} />;
}

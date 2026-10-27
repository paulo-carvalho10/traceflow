import type { Metadata } from "next";

import { RulesView } from "@/components/incidents/rules-view";

export const metadata: Metadata = { title: "Regras de detecção" };

export default async function RulesPage({ params }: PageProps<"/projects/[projectId]/settings/rules">) {
  const { projectId } = await params;
  return <RulesView projectId={Number(projectId)} />;
}

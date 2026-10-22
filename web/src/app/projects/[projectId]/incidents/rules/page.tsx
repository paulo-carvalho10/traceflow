import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { RulesView } from "@/components/incidents/rules-view";

export const metadata: Metadata = { title: "Regras de detecção" };

export default async function RulesPage({ params }: PageProps<"/projects/[projectId]/incidents/rules">) {
  const { projectId } = await params;
  return (
    <>
      <PageHeader title="Regras de detecção" description="O que conta como degradado e como falhando, em cada projeto." />
      <RulesView projectId={Number(projectId)} />
    </>
  );
}

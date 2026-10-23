import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { PlaygroundView } from "@/components/playground/playground-view";

export const metadata: Metadata = { title: "Incident Playground" };

export default async function PlaygroundPage({ params }: PageProps<"/projects/[projectId]/playground">) {
  const { projectId } = await params;
  return (
    <>
      <PageHeader
        title="Incident Playground"
        description="Quebre a loja de propósito e acompanhe o incidente nascer, ser investigado e se resolver."
      />
      <PlaygroundView projectId={Number(projectId)} />
    </>
  );
}

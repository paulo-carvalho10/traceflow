import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { KeysManager } from "@/components/keys-manager";

export const metadata: Metadata = { title: "Chaves de ingestão" };

export default async function KeysPage({ params }: PageProps<"/projects/[projectId]/settings/keys">) {
  const { projectId } = await params;
  return (
    <>
      <PageHeader title="Chaves de ingestão" description="Como as suas aplicações provam de qual projeto são os spans." />
      <KeysManager projectId={Number(projectId)} />
    </>
  );
}

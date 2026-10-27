import type { Metadata } from "next";

import { KeysManager } from "@/components/keys-manager";

export const metadata: Metadata = { title: "Chaves de ingestão" };

export default async function KeysPage({ params }: PageProps<"/projects/[projectId]/settings/keys">) {
  const { projectId } = await params;
  return <KeysManager projectId={Number(projectId)} />;
}

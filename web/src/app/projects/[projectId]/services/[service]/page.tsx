import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/app-shell";
import { ServiceView } from "@/components/dashboard/service-view";

export const metadata: Metadata = { title: "Serviço" };

export default async function ServicePage({ params }: PageProps<"/projects/[projectId]/services/[service]">) {
  const { projectId, service } = await params;
  const name = decodeURIComponent(service);
  return (
    <>
      <PageHeader title={name} description="Como este serviço está agora e como esteve no período escolhido." />
      <Suspense>
        <ServiceView projectId={Number(projectId)} service={name} />
      </Suspense>
    </>
  );
}

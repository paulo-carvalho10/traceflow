import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { ServiceView } from "@/components/dashboard/service-view";

export const metadata: Metadata = { title: "Serviço" };

export default async function ServicePage({ params }: PageProps<"/projects/[projectId]/services/[service]">) {
  const { service } = await params;
  const name = decodeURIComponent(service);
  return (
    <>
      <PageHeader title={<span className="font-mono">{name}</span>} description="Como este serviço está agora, como esteve no período, e do que ele depende." />
      <ServiceView service={name} />
    </>
  );
}

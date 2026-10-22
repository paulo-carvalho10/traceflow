import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/app-shell";
import { ServiceMapView } from "@/components/map/service-map-view";

export const metadata: Metadata = { title: "Mapa de serviços" };

export default async function MapPage({ params }: PageProps<"/projects/[projectId]/map">) {
  const { projectId } = await params;
  return (
    <>
      <PageHeader
        title="Mapa de serviços"
        description="Quem chama quem, desenhado a partir dos próprios traces, sem configuração."
      />
      <Suspense>
        <ServiceMapView projectId={Number(projectId)} />
      </Suspense>
    </>
  );
}

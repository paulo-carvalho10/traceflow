import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/app-shell";
import { DashboardView } from "@/components/dashboard/dashboard-view";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage({ params }: PageProps<"/projects/[projectId]/dashboard">) {
  const { projectId } = await params;
  return (
    <>
      <PageHeader title="Dashboard" description="O sistema agora: o que entra, como cada serviço está respondendo." />
      <Suspense>
        <DashboardView projectId={Number(projectId)} />
      </Suspense>
    </>
  );
}

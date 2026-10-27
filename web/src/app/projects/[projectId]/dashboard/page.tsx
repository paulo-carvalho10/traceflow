import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { DashboardView } from "@/components/dashboard/dashboard-view";

export const metadata: Metadata = { title: "Visão geral" };

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="Visão geral" description="Como o sistema está agora, e como chegou até aqui." />
      <DashboardView />
    </>
  );
}

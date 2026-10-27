import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { ServicesView } from "@/components/services/services-view";

export const metadata: Metadata = { title: "Serviços" };

export default function ServicesPage() {
  return (
    <>
      <PageHeader title="Serviços" description="Cada serviço que mandou spans neste ambiente: a saúde e os números de agora." />
      <ServicesView />
    </>
  );
}

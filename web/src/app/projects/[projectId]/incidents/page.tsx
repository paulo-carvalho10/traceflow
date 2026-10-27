import type { Metadata } from "next";

import { PageHeader } from "@/components/app-shell";
import { IncidentsView } from "@/components/incidents/incidents-view";

export const metadata: Metadata = { title: "Incidentes" };

export default function IncidentsPage() {
  return (
    <>
      <PageHeader
        title="Incidentes"
        description="Abertos sozinhos quando um serviço sai de saudável por 3 s, com a causa provável, o impacto e a severidade."
      />
      <IncidentsView />
    </>
  );
}

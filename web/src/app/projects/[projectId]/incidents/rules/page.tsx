import { redirect } from "next/navigation";

// as regras moraram aqui até a Etapa 10; agora ficam nas configurações
export default async function OldRulesPage({ params }: PageProps<"/projects/[projectId]/incidents/rules">) {
  const { projectId } = await params;
  redirect(`/projects/${projectId}/settings/rules`);
}

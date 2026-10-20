import { redirect } from "next/navigation";

// /projects/7 vai direto para os traces (o dashboard chega na Etapa 6)
export default async function ProjectHome({ params }: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  redirect(`/projects/${projectId}/traces`);
}

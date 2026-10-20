import { redirect } from "next/navigation";

// /projects/7 vai direto para o dashboard
export default async function ProjectHome({ params }: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  redirect(`/projects/${projectId}/dashboard`);
}

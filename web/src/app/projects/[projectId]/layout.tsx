import { AppShell } from "@/components/app-shell";

// Componente de servidor: só lê o id da URL e entrega para a moldura (que roda no navegador).
// No Next.js 16, params chega como Promise: a rota pode começar a renderizar antes de tê-lo.
export default async function ProjectLayout({ children, params }: LayoutProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  return <AppShell projectId={Number(projectId)}>{children}</AppShell>;
}

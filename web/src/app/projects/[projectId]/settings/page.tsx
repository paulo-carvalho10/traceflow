import type { Metadata } from "next";

import { ProjectSettings } from "@/components/settings/project-settings";

export const metadata: Metadata = { title: "Configurações" };

export default function SettingsPage() {
  return <ProjectSettings />;
}

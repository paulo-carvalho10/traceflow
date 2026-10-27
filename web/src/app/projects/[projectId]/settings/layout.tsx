import { PageHeader } from "@/components/app-shell";
import { SettingsNav } from "@/components/settings/settings-nav";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Configurações" description="O projeto, as chaves com que as aplicações mandam spans e as regras de detecção." />
      <SettingsNav />
      {children}
    </>
  );
}

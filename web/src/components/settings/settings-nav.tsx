"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useWorkspace } from "@/components/workspace";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { href: "", label: "Projeto" },
  { href: "/keys", label: "Chaves de ingestão" },
  { href: "/rules", label: "Regras de detecção" },
];

/** As seções das configurações, em abas que são links (cada uma tem o seu endereço). */
export function SettingsNav() {
  const pathname = usePathname();
  const { projectId } = useWorkspace();
  const base = `/projects/${projectId}/settings`;
  return (
    <nav className="flex gap-1 border-b px-4 sm:px-6" aria-label="Seções das configurações">
      {SECTIONS.map((s) => {
        const href = `${base}${s.href}`;
        const active = pathname === href;
        return (
          <Link
            key={s.href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "-mb-px border-b-2 px-2.5 py-2 text-[13px] transition-colors duration-100",
              active ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {s.label}
          </Link>
        );
      })}
    </nav>
  );
}

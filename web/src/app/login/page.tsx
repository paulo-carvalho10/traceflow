import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = { title: "Entrar" };

// Suspense: o formulário lê a URL (?next=...), e o Next.js pede essa fronteira para poder
// gerar o resto da página sem esperar pelo navegador
export default function LoginPage() {
  return (
    <Suspense>
      <AuthForm mode="login" />
    </Suspense>
  );
}

"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { DemoButton } from "@/components/demo-button";
import { Logo } from "@/components/logo";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";

/** O formulário de login e o de cadastro: o mesmo componente, com um campo a mais no cadastro. */
export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = useMutation({
    mutationFn: () => (mode === "login" ? api.login(email, password) : api.register(name, email, password)),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
      // só segue para caminhos internos: um "next=https://site-falso" não pode virar redirecionamento
      router.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/projects");
    },
    meta: { silent: true },
  });

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-6 flex justify-center">
          <Logo />
        </Link>
        <Card>
          <CardHeader>
            <CardTitle>{mode === "login" ? "Entrar" : "Criar conta"}</CardTitle>
            <CardDescription>
              {mode === "login" ? "Acompanhe os seus projetos." : "Um projeto e uma chave, e seus traces começam a chegar."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault(); // o formulário não recarrega a página: quem envia é o React
                submit.mutate();
              }}
            >
              {mode === "register" && (
                <div className="space-y-2">
                  <Label htmlFor="name">Nome</Label>
                  <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="email">E-mail</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Senha</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  minLength={mode === "register" ? 10 : undefined}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                {mode === "register" && <p className="text-xs text-muted-foreground">Pelo menos 10 caracteres.</p>}
              </div>
              {submit.error && (
                <Alert variant="destructive">
                  <AlertDescription>{submit.error.message}</AlertDescription>
                </Alert>
              )}
              <Button type="submit" className="w-full" disabled={submit.isPending}>
                {submit.isPending ? "Aguarde…" : mode === "login" ? "Entrar" : "Criar conta"}
              </Button>
            </form>
            <div className="mt-6 space-y-3 text-center text-sm text-muted-foreground">
              {mode === "login" ? (
                <p>
                  Não tem conta?{" "}
                  <Link className="text-primary hover:underline" href="/cadastro">
                    Criar conta
                  </Link>
                </p>
              ) : (
                <p>
                  Já tem conta?{" "}
                  <Link className="text-primary hover:underline" href="/login">
                    Entrar
                  </Link>
                </p>
              )}
              <div className="flex justify-center">
                <DemoButton size="default" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

/** Entra como visitante (sem cadastro) e abre o projeto da loja de demonstração. */
export function DemoButton({ size = "lg" }: { size?: "default" | "lg" }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const enter = useMutation({
    mutationFn: api.demo,
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
      router.push("/projects/1/dashboard");
    },
  });
  return (
    <Button size={size} onClick={() => enter.mutate()} disabled={enter.isPending}>
      {enter.isPending ? "Entrando…" : "Ver a demonstração"}
      <ArrowRight className="size-4" />
    </Button>
  );
}

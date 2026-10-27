import type { Metadata } from "next";

import { TraceView } from "@/components/traces/trace-view";

export const metadata: Metadata = { title: "Trace" };

export default async function TracePage({ params, searchParams }: PageProps<"/projects/[projectId]/traces/[traceId]">) {
  const { projectId, traceId } = await params;
  const around = (await searchParams).around;
  return <TraceView projectId={Number(projectId)} traceId={traceId} around={typeof around === "string" ? around : undefined} />;
}

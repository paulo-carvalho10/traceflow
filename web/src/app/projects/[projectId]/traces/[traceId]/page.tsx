import type { Metadata } from "next";
import { Suspense } from "react";

import { TraceView } from "@/components/traces/trace-view";

export const metadata: Metadata = { title: "Trace" };

export default async function TracePage({ params }: PageProps<"/projects/[projectId]/traces/[traceId]">) {
  const { projectId, traceId } = await params;
  return (
    <Suspense>
      <TraceView projectId={Number(projectId)} traceId={traceId} />
    </Suspense>
  );
}

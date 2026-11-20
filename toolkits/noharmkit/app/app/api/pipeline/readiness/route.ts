import { NextResponse } from "next/server";
import { pipelineReadiness } from "@/lib/pipeline-readiness";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(): NextResponse {
  return NextResponse.json(pipelineReadiness(), { headers: { "Cache-Control": "no-store" } });
}

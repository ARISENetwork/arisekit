import { ApiConfigImpactError } from "@/lib/api-config-impact";
import { NextRequest, NextResponse } from "next/server";
import { projectFailureStatus } from "@/lib/project-files";
import { parseApiPipelineConfig } from "@/lib/api-pipeline-config";
import { saveApiPipelineConfig, validateApiModels } from "@/lib/api-pipeline-store";
import { loadOpenRouterModels } from "@/lib/openrouter-models";
import { requestOrigin } from "@/lib/request-origin";
import { casesetDir, projectsRoot } from "@/lib/caseset/paths";
import { readPipelineRecord } from "@/lib/pipeline-workspace";
import type { PipelineRunRecord } from "@/lib/pipeline-runner";
import { getCurrent } from "@/lib/caseset/current";
import { loadModelSetup } from "@/lib/api-model-setup";

export const dynamic = "force-dynamic";

// The model setup popup loads the current project's setup and the model catalog here.
export async function GET(): Promise<NextResponse> {
  try {
    const current = await getCurrent();
    if (!current) return NextResponse.json({ error: "Choose a project first." }, { status: 404 });
    return NextResponse.json(await loadModelSetup(current), { headers: { "Cache-Control": "no-store" } });
  } catch (caught) {
    return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, 500) });
  }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(requestOrigin(request)).origin) return NextResponse.json({ error: "API setup must come from this site." }, { status: 403 });
  try {
    const body = await request.json();
    if (typeof body.project !== "string") throw new TypeError("Choose a project.");
    const config = parseApiPipelineConfig(body.config);
    const root = projectsRoot();
    const last = readPipelineRecord<PipelineRunRecord>(casesetDir(root, body.project), "latest.json");
    if (last?.status === "running") return NextResponse.json({ error: "Finish or resolve the current pipeline run before changing its model setup." }, { status: 409 });
    validateApiModels(config, await loadOpenRouterModels());
    saveApiPipelineConfig(root, body.project, config);

    return NextResponse.json({ saved: true, href: "/noharm/dataset" });
  } catch (caught) {
    if (caught instanceof ApiConfigImpactError) return NextResponse.json({ error: caught.message, impact: caught.impact }, { status: 409 });
    return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, caught instanceof TypeError || caught instanceof SyntaxError ? 400 : 500) });
  }
}

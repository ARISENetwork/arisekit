import { projectsRoot } from "@/lib/caseset/paths";
import { NextRequest, NextResponse } from "next/server";
import { projectFailureStatus } from "@/lib/project-files";
import { forkApiRun } from "@/lib/api-config-fork";
import { parseApiPipelineConfig } from "@/lib/api-pipeline-config";
import { validateApiModels } from "@/lib/api-pipeline-store";
import { BENCHMARK_COOKIE } from "@/lib/caseset/selection";
import { loadOpenRouterModels } from "@/lib/openrouter-models";
import { requestOrigin } from "@/lib/request-origin";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(requestOrigin(request)).origin) return NextResponse.json({ error: "New run creation must come from this site." }, { status: 403 });
  try {
    const body = await request.json();
    if (typeof body.project !== "string" || typeof body.name !== "string") throw new TypeError("Choose a source project and a new run name.");
    const config = parseApiPipelineConfig(body.config);
    const root = projectsRoot();
    validateApiModels(config, await loadOpenRouterModels());
    forkApiRun(root, body.project, body.name, config);

    const response = NextResponse.json({ project: body.name, href: "/noharm/dataset" }, { status: 201 });
    response.cookies.set(BENCHMARK_COOKIE, body.name, { httpOnly: true, path: "/", sameSite: "lax", maxAge: 60 * 60 * 24 * 365 });
    return response;
  } catch (caught) {
    const error = caught as Error & { code?: string };
    return NextResponse.json({ error: error.code === "EEXIST" ? "That run name already exists. Choose another name." : error.message }, { status: projectFailureStatus(error, error.code === "EEXIST" ? 409 : error instanceof TypeError || error instanceof SyntaxError ? 400 : 500) });
  }
}

import { NextRequest, NextResponse } from "next/server";
import { projectFailureStatus } from "@/lib/project-files";
import { loadApiPipelineConfig } from "@/lib/api-pipeline-store";
import { BENCHMARK_COOKIE } from "@/lib/caseset/selection";
import { casesetDir, projectsRoot } from "@/lib/caseset/paths";
import { inspectRecovery, newRecoveryRun, type RecoveryTicket } from "@/lib/pipeline-recovery";
import { pipelinePython } from "@/lib/pipeline-runner";
import { readProjectMode } from "@/lib/project-mode-store";
import { isTutorialProject } from "@/lib/onboarding";
import { requestOrigin } from "@/lib/request-origin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function recoveryContext(project: string) {
  if (project === "demo" || isTutorialProject(project)) throw new TypeError("Prepared examples cannot be recovered or copied into execution runs.");
  const root = projectsRoot();
  const directory = casesetDir(root, project);
  if (readProjectMode(root, project) !== "api") throw new TypeError("Recovery is available for API Mode projects.");

  const key = `local:${directory}`;
  const config = loadApiPipelineConfig(root, project);
  if (!config) throw new TypeError("Save the API model setup before reviewing a run.");
  return { directory, key, config };
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const project = request.nextUrl.searchParams.get("project") ?? "";
    const { directory, key, config } = recoveryContext(project);
    const { plan } = await inspectRecovery(directory, key, config, pipelinePython());
    return NextResponse.json({ plan }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) { return NextResponse.json({ error: (error as Error).message }, { status: projectFailureStatus(error, 400) }); }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(requestOrigin(request)).origin) return NextResponse.json({ error: "Run recovery must come from this site." }, { status: 403 });
  try {
    const body = await request.json() as { project: string; name: string; ticket: RecoveryTicket };
    if (typeof body.project !== "string" || typeof body.name !== "string" || typeof body.ticket?.jobId !== "string" || typeof body.ticket?.token !== "string") throw new TypeError("Review saved work and choose a name for the new run.");
    const { directory, key, config } = recoveryContext(body.project);
    const inspection = await inspectRecovery(directory, key, config, pipelinePython());
    const root = projectsRoot();
    newRecoveryRun(root, body.project, body.name, inspection, body.ticket, config);

    const response = NextResponse.json({ project: body.name, href: "/noharm/api-setup" }, { status: 201 });
    response.cookies.set(BENCHMARK_COOKIE, body.name, { httpOnly: true, path: "/", sameSite: "lax", maxAge: 60 * 60 * 24 * 365 });
    return response;
  } catch (error) { return NextResponse.json({ error: (error as Error).message }, { status: projectFailureStatus(error, (error as NodeJS.ErrnoException).code === "EEXIST" ? 409 : 400) }); }
}

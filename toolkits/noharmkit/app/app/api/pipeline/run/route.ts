import { NextRequest, NextResponse } from "next/server";
import { projectFailureStatus } from "@/lib/project-files";
import { casesetDir, inside, projectsRoot } from "@/lib/caseset/paths";
import { parseApiPipelineAction } from "@/lib/api-pipeline-action";
import { addResponsePrompt, loadApiPipelineConfig, validateApiModels } from "@/lib/api-pipeline-store";
import { createPipelineWorkspace } from "@/lib/pipeline-workspace";
import { currentPipelineRun, executePipeline, pipelinePython, stopPipelineRun, type PipelineEvent } from "@/lib/pipeline-runner";
import { readProjectMode } from "@/lib/project-mode-store";
import { loadOpenRouterModels } from "@/lib/openrouter-models";
import { openRouterApiKey } from "@/lib/openrouter-key";
import { requestOrigin } from "@/lib/request-origin";
import { readFileSync, existsSync } from "node:fs";
import { isTutorialProject } from "@/lib/onboarding";
import { inspectRecovery, restoreRecovery } from "@/lib/pipeline-recovery";
import { loadPrompts } from "@/lib/response-prompts";
import { ApiConfigImpactError } from "@/lib/api-config-impact";
import { emptyApiPipelineConfig } from "@/lib/api-pipeline-config";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const project = request.nextUrl.searchParams.get("project") ?? "";

    const root = projectsRoot();
    const directory = casesetDir(root, project);
    const key = `local:${directory}`;
    return NextResponse.json({ run: currentPipelineRun(directory, key) }, { headers: { "Cache-Control": "no-store" } });
  } catch (caught) {
    return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, 400) });
  }
}

export async function POST(request: NextRequest): Promise<Response> {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(requestOrigin(request)).origin) return NextResponse.json({ error: "Pipeline execution must come from this site." }, { status: 403 });
  try {
    const body = await request.json();
    if (typeof body.project !== "string") throw new TypeError("Choose a project.");
    const action = parseApiPipelineAction(body.action);
    const python = pipelinePython();
    const workspace = createPipelineWorkspace(body.project);
    const rescore = action.stage === "score" && action.allowPartial === true;
    if (!rescore && readProjectMode(workspace.root, body.project) !== "api") throw new TypeError("This project uses Local Mode. Run stages with your local coding agent or switch to API Mode.");
    const provenancePath = inside(workspace.directory, "provenance.json");
    const provenance = existsSync(provenancePath) ? JSON.parse(readFileSync(provenancePath, "utf8")) : {};
    if (isTutorialProject(body.project) || body.project === "demo" && provenance.synthetic === true) throw new TypeError("The prepared demo is read-only. Create your own project before running models.");
    let config = loadApiPipelineConfig(workspace.root, body.project) ?? (rescore ? emptyApiPipelineConfig() : undefined);
    if (!config) return NextResponse.json({ error: "Choose the models for each pipeline step before running.", href: "/noharm/api-setup" }, { status: 409 });
    if (action.prompt !== undefined) {
      if (!loadPrompts(workspace.root, body.project).some(prompt => prompt.id === action.prompt)) throw new TypeError(`Prompt ${action.prompt} is not saved in this project.`);
      config = addResponsePrompt(workspace.root, body.project, config, action.prompt);
    }
    let recoveredFrom: string | undefined;
    let needsProvider = action.stage !== "score";
    if (body.recovery !== undefined) {
      if (typeof body.recovery?.jobId !== "string" || typeof body.recovery?.token !== "string") throw new TypeError("Review saved work before resuming this run.");
      const inspection = await inspectRecovery(workspace.directory, workspace.key, config, python);
      if (!inspection.record || JSON.stringify(action) !== JSON.stringify(parseApiPipelineAction(inspection.record.action))) throw new TypeError("Recovery must use the inspected stage and scope.");
      restoreRecovery(workspace, inspection, body.recovery);
      recoveredFrom = inspection.record.jobId;
      needsProvider = needsProvider && inspection.plan.pending !== false;
    }
    if (needsProvider) validateApiModels(config, await loadOpenRouterModels(), action.stage);
    const apiKey = openRouterApiKey();
    if (needsProvider && !apiKey) return NextResponse.json({ error: "Configure OPENROUTER_API_KEY in the server environment before running API stages." }, { status: 503 });
    const controller = new AbortController();
    const abort = (): void => controller.abort();
    request.signal.addEventListener("abort", abort, { once: true });
    if (request.signal.aborted) controller.abort();
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      async start(output) {
        let connected = true;
        const emit = (event: PipelineEvent): void => { if (connected) { try { output.enqueue(encoder.encode(`${JSON.stringify(event)}\n`)); } catch { connected = false; controller.abort(); } } };
        try { await executePipeline(workspace, action, config, { apiKey: apiKey ?? "", python, signal: controller.signal, emit, recoveredFrom }); }
        catch (caught) { emit({ type: "result", status: "failed", error: (caught as Error).message }); }
        finally { request.signal.removeEventListener("abort", abort); if (connected) output.close(); }
      },
      cancel() { controller.abort(); },
    });
    return new Response(stream, { headers: { "Content-Type": "application/x-ndjson", "Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no" } });
  } catch (caught) {
    return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, caught instanceof TypeError ? 400 : caught instanceof ApiConfigImpactError ? 409 : 500) });
  }
}

export async function PATCH(request: NextRequest): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(requestOrigin(request)).origin) return NextResponse.json({ error: "Pipeline control must come from this site." }, { status: 403 });
  try {
    const body = await request.json();
    if (typeof body.project !== "string" || typeof body.jobId !== "string" || !body.jobId) throw new TypeError("Choose an active project run to stop.");

    const root = projectsRoot();
    const directory = casesetDir(root, body.project);
    const key = `local:${directory}`;
    const run = currentPipelineRun(directory, key);
    if (!run || run.status !== "running" || run.jobId !== body.jobId) return NextResponse.json({ error: "This run is no longer active. Check saved status before continuing." }, { status: 409 });
    return NextResponse.json({ run: stopPipelineRun(key, body.jobId) });
  } catch (caught) {
    return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, caught instanceof TypeError || caught instanceof SyntaxError ? 400 : 409) });
  }
}

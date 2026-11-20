import { projectsRoot } from "@/lib/caseset/paths";
import { requestOrigin } from "@/lib/request-origin";
import { projectFailureStatus } from "@/lib/project-files";
import { readProjectMode, saveProjectMode } from "@/lib/project-mode-store";
import { loadApiPipelineConfig } from "@/lib/api-pipeline-store";
import { NextRequest, NextResponse } from "next/server";

import { listBenchmarks, loadBenchmark } from "@/lib/caseset/metrics";
import { BENCHMARK_COOKIE, safeBenchmarkReturnPath } from "@/lib/caseset/selection";
import { isTutorialProject } from "@/lib/onboarding";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const benchmark = request.nextUrl.searchParams.get("benchmark") ?? "";
  if (!isTutorialProject(benchmark)) return NextResponse.json({ error: "Expected a tutorial project." }, { status: 400 });
  const root = projectsRoot();
  if (!listBenchmarks(root).includes(benchmark)) return NextResponse.json({ ready: false });
  const { cases } = loadBenchmark(root, benchmark);
  return NextResponse.json({ ready: cases.length > 0 && cases.every((item) => item.rubric.hasPassing) }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  // Next.js uses the bind address in nextUrl when the server listens on all interfaces.
  const site = new URL(requestOrigin(request));
  const origin = request.headers.get("origin");
  if (origin && origin !== site.origin) {
    return NextResponse.json({ error: "Project selection must come from this site." }, { status: 403 });
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json({ error: "Project selection requires a form." }, { status: 400 });
  }
  const benchmark = form.get("benchmark");
  try {
    const root = projectsRoot();
    if (typeof benchmark !== "string" || !listBenchmarks(root).includes(benchmark)) {
      return NextResponse.json({ error: "Unknown project." }, { status: 400 });
    }
    if (form.has("execution_mode")) saveProjectMode(root, benchmark, form.get("execution_mode"));

    const prepared = isTutorialProject(benchmark) || benchmark === "demo" && loadBenchmark(root, benchmark).cases.some(item => item.page.provenance.synthetic === true);
    const needsSetup = form.has("execution_mode") && readProjectMode(root, benchmark) === "api" && !prepared && !loadApiPipelineConfig(root, benchmark);
    const href = needsSetup ? "/noharm/api-setup" : safeBenchmarkReturnPath(form.get("returnTo"));
    const response = request.headers.get("accept")?.includes("application/json")
      ? NextResponse.json({ project: benchmark, href })
      : NextResponse.redirect(new URL(href, site.origin), 303);
    response.cookies.set(BENCHMARK_COOKIE, benchmark, {
      httpOnly: true,
      path: "/",
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 365,
    });
    return response;
  } catch (caught) {
    const error = caught as Error;
    return NextResponse.json({ error: error.message }, { status: projectFailureStatus(error, error instanceof TypeError || error instanceof SyntaxError ? 400 : 500) });
  }
}

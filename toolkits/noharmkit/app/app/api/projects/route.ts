import { projectsRoot } from "@/lib/caseset/paths";
import { requestOrigin } from "@/lib/request-origin";
import { projectFailureStatus } from "@/lib/project-files";
import { NextRequest, NextResponse } from "next/server";
import { BENCHMARK_COOKIE } from "@/lib/caseset/selection";
import { createProject } from "@/lib/project-create";
import { projectMode } from "@/lib/project-mode";
import { readProjectMode } from "@/lib/project-mode-store";
import { importProject } from "@/lib/project-import";
import { listBenchmarks } from "@/lib/caseset/metrics";
import { archiveProject, deletionBlock, saveProjectInfo } from "@/lib/project-manage";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const site = new URL(requestOrigin(request));
  const origin = request.headers.get("origin");
  if (origin && origin !== site.origin) return NextResponse.json({ error: "Project creation must come from this site." }, { status: 403 });
  try {
    const body = await request.json();
    if (typeof body.name !== "string" || (body.files === undefined && typeof body.idea !== "string")) throw new TypeError("Provide a project name and benchmark idea text, or a project folder.");
    const root = projectsRoot();
    let mode: ReturnType<typeof projectMode>;
    if (body.files !== undefined) {
      importProject(root, body.name, body.files);
      mode = readProjectMode(root, body.name);
    } else {
      mode = projectMode(body.execution_mode);
      createProject(root, body.name, body.idea, mode);
    }

    const response = NextResponse.json({ project: body.name, href: body.files !== undefined ? "/noharm/dashboard" : mode === "api" ? "/noharm/api-setup" : "/noharm/dataset" }, { status: 201 });
    response.cookies.set(BENCHMARK_COOKIE, body.name, { httpOnly: true, path: "/", sameSite: "lax", maxAge: 60 * 60 * 24 * 365 });
    return response;
  } catch (caught) {
    const error = caught as Error & { code?: string };
    const status = projectFailureStatus(error, error.code === "EEXIST" ? 409 : error instanceof TypeError || error instanceof SyntaxError ? 400 : 500);
    return NextResponse.json({ error: error.code === "EEXIST" ? "This project already exists. Choose another name or resume it." : error.message }, { status });
  }
}

function sameSite(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  return !origin || origin === new URL(requestOrigin(request)).origin;
}

async function knownProject(request: NextRequest): Promise<{ name: string; body: Record<string, unknown>; root: string }> {
  const body = await request.json() as Record<string, unknown>;
  const root = projectsRoot();
  if (typeof body.name !== "string" || !listBenchmarks(root).includes(body.name)) throw new TypeError("Unknown project.");
  return { name: body.name, body, root };
}

// Saves a project's display name or note.
export async function PATCH(request: NextRequest): Promise<NextResponse> {
  if (!sameSite(request)) return NextResponse.json({ error: "Project changes must come from this site." }, { status: 403 });
  try {
    const { name, body, root } = await knownProject(request);
    const info = saveProjectInfo(root, name, Object.fromEntries(Object.entries(body).filter(([key]) => key === "title" || key === "note")));

    return NextResponse.json({ project: name, ...info });
  } catch (caught) {
    const error = caught as Error;
    return NextResponse.json({ error: error.message }, { status: projectFailureStatus(error, error instanceof TypeError || error instanceof SyntaxError ? 400 : 500) });
  }
}

// Archived projects can be recovered from projects/.deleted/.
export async function DELETE(request: NextRequest): Promise<NextResponse> {
  if (!sameSite(request)) return NextResponse.json({ error: "Project changes must come from this site." }, { status: 403 });
  try {
    const { name, root } = await knownProject(request);
    const blocked = deletionBlock(root, name);
    if (blocked) return NextResponse.json({ error: blocked }, { status: 409 });
    const movedTo = archiveProject(root, name);
    return NextResponse.json({ deleted: name, movedTo });
  } catch (caught) {
    const error = caught as Error;
    return NextResponse.json({ error: error.message }, { status: projectFailureStatus(error, error instanceof TypeError || error instanceof SyntaxError ? 400 : 500) });
  }
}

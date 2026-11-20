import { requestOrigin } from "@/lib/request-origin";
import { projectFailureStatus } from "@/lib/project-files";
import { NextRequest, NextResponse } from "next/server";
import { NotFoundError, projectsRoot } from "@/lib/caseset/paths";
import { DatasetDraftConflict, readDatasetDrafts, saveDatasetDrafts } from "@/lib/dataset-drafts";

function failure(caught: unknown): NextResponse {
  return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, caught instanceof DatasetDraftConflict ? 409 : caught instanceof NotFoundError ? 404 : caught instanceof TypeError || caught instanceof SyntaxError ? 400 : 500) });
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const project = request.nextUrl.searchParams.get("project");
  if (!project) return NextResponse.json({ error: "Choose the project to load drafts." }, { status: 400 });
  try { return NextResponse.json(readDatasetDrafts(projectsRoot(), project), { headers: { "Cache-Control": "no-store" } }); }
  catch (caught) { return failure(caught); }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const site = new URL(requestOrigin(request));
  const origin = request.headers.get("origin");
  if (origin && origin !== site.origin) return NextResponse.json({ error: "Draft saves must come from this site." }, { status: 403 });
  try {
    const { project, state } = await request.json();
    if (typeof project !== "string" || !project) throw new TypeError("Choose the project to save drafts.");
    const root = projectsRoot();
    const result = saveDatasetDrafts(root, project, state);

    return NextResponse.json(result);
  } catch (caught) { return failure(caught); }
}

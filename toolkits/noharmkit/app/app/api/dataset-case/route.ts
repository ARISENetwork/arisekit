import { requestOrigin } from "@/lib/request-origin";
import { projectFailureStatus } from "@/lib/project-files";
import { NextRequest, NextResponse } from "next/server";
import { NotFoundError, projectsRoot } from "@/lib/caseset/paths";
import { DatasetEditConflict, saveDatasetCase } from "@/lib/dataset-edit";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const site = new URL(requestOrigin(request));
  const origin = request.headers.get("origin");
  if (origin && origin !== site.origin) return NextResponse.json({ error: "Dataset edits must come from this site." }, { status: 403 });
  try {
    const { project, id, value, basis } = await request.json();
    if (typeof project !== "string" || typeof id !== "string" || !value || !basis) return NextResponse.json({ error: "Provide the project, case, and original fields." }, { status: 400 });
    const root = projectsRoot();
    saveDatasetCase(root, project, id, value, basis);

    return NextResponse.json({ saved: true });
  } catch (caught) {
    return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, caught instanceof DatasetEditConflict ? 409 : caught instanceof NotFoundError ? 404 : 400) });
  }
}

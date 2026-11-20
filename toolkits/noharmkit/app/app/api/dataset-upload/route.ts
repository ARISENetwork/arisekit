import { requestOrigin } from "@/lib/request-origin";
import { projectFailureStatus } from "@/lib/project-files";
import { NextRequest, NextResponse } from "next/server";
import { listCasesetNames, NotFoundError, projectsRoot } from "@/lib/caseset/paths";
import { saveDatasetUpload } from "@/lib/dataset-upload";

export async function GET(): Promise<NextResponse> {
  return NextResponse.json({ projects: listCasesetNames(projectsRoot()) }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const site = new URL(requestOrigin(request));
  const origin = request.headers.get("origin");
  if (origin && origin !== site.origin) return NextResponse.json({ error: "Dataset upload must come from this site." }, { status: 403 });
  try {
    const form = await request.formData();
    const project = form.get("project"), file = form.get("file");
    if (typeof project !== "string" || !project) return NextResponse.json({ error: "Choose the destination project." }, { status: 400 });
    if (!(file instanceof File)) return NextResponse.json({ error: "Choose a CSV or JSON file." }, { status: 400 });
    const bytes = new Uint8Array(await file.arrayBuffer());
    const root = projectsRoot();
    const upload = saveDatasetUpload(root, project, file.name, bytes);

    return NextResponse.json(upload, { status: 201 });
  } catch (caught) {
    const status = caught instanceof NotFoundError ? 404 : caught instanceof TypeError ? 400 : 500;
    return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, status) });
  }
}

import { NextRequest, NextResponse } from "next/server";
import { projectFailureStatus } from "@/lib/project-files";
import { NotFoundError, projectsRoot } from "@/lib/caseset/paths";
import { projectArchiveStream, projectExportInventory } from "@/lib/project-export";

export const runtime = "nodejs";

export async function GET(request: NextRequest): Promise<Response> {
  try {
    const project = request.nextUrl.searchParams.get("project");
    if (!project || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(project)) throw new TypeError("Choose a valid project.");
    const root = projectsRoot();
    const { folder, manifest } = await projectExportInventory(root, project);
    return new Response(projectArchiveStream(folder, manifest), { headers: {
      "Content-Type": "application/gzip",
      "Content-Disposition": `attachment; filename="${project}-project.tar.gz"`,
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    } });
  } catch (caught) {
    return NextResponse.json({ error: (caught as Error).message }, { status: projectFailureStatus(caught, caught instanceof NotFoundError ? 404 : caught instanceof TypeError ? 400 : 500) });
  }
}

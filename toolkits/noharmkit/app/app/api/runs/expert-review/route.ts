import { projectsRoot } from "@/lib/caseset/paths";
import { NextRequest, NextResponse } from "next/server";
import { projectFailureStatus } from "@/lib/project-files";
import { httpStatus } from "@/lib/caseset/editor";
import { createProjectReviewPacket, createReviewPacket, importPortableReview, planReviewImport, retainProjectSubmission } from "@/lib/caseset/portable-review";
import { buildPortableHtml } from "@/lib/portable-build";
import { expandPortableReviews } from "@/lib/portable-review";
import { requestOrigin } from "@/lib/request-origin";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: NextRequest): Promise<Response> {
  try {
    const q = request.nextUrl.searchParams;
    const root = projectsRoot();
    const packet = q.get("scope") === "project"
      ? createProjectReviewPacket(root, q.get("project") ?? "", q.get("version") ?? "")
      : createReviewPacket(root, q.get("project") ?? "", q.get("caseId") ?? "", q.get("version") ?? "");
    const name = packet.format === "noharm-project-review-packet-v1" ? packet.project : packet.caseId;
    return new Response(await buildPortableHtml(packet), { headers: {
      "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
      "Content-Disposition": `attachment; filename="${name}.${packet.version}.expert-review.html"`,
    } });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: projectFailureStatus(error, httpStatus(error)) });
  }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (origin && origin !== requestOrigin(request)) return NextResponse.json({ error: "Review imports must come from this site." }, { status: 403 });
  try {
    const body = await request.json() as { project: string; reviews: unknown[]; preview: boolean };
    if (!body || typeof body.project !== "string" || !Array.isArray(body.reviews) || !body.reviews.length || typeof body.preview !== "boolean") throw new Error("Choose at least one review file and preview it before importing.");
    const root = projectsRoot();
    const reviews = body.reviews.flatMap(expandPortableReviews);
    const results = reviews.map((review) => planReviewImport(root, body.project, review));
    const identities = results.map((result) => `${result.caseId}/${result.reviewer}`);
    if (new Set(identities).size !== identities.length) throw new Error("The selection contains multiple submissions for the same case and reviewer. Import each expert's independent submission once.");
    if (body.preview) return NextResponse.json({ results });
    const imported = reviews.map((review) => importPortableReview(root, body.project, review));
    for (const value of body.reviews) {
      if ((value as { format?: string } | null)?.format === "noharm-project-expert-review-v1") retainProjectSubmission(root, body.project, value);
    }

    return NextResponse.json({ results: imported });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: projectFailureStatus(error, httpStatus(error)) });
  }
}

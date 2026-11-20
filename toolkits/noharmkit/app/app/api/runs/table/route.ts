import { requestOrigin } from "@/lib/request-origin";
import { projectFailureStatus } from "@/lib/project-files";
import { NextRequest, NextResponse } from "next/server";

import type { TextV2Case } from "@/lib/rubric-text-v2";
import type { AnswerTableCase, AuthoringTiming } from "@/lib/answer-table";
import { httpStatus, loadEditorPayload, saveReviewedTable } from "@/lib/caseset/editor";
import { projectsRoot } from "@/lib/caseset/paths";
import { TUTORIAL_PROJECT, tutorialBenchmark } from "@/lib/uti-tutorial-benchmark";

export const dynamic = "force-dynamic";

function failure(error: unknown): NextResponse {
  return NextResponse.json({ error: (error as Error).message }, { status: projectFailureStatus(error, httpStatus(error)) });
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const q = request.nextUrl.searchParams;
  if (q.get("caseset") === TUTORIAL_PROJECT) {
    try {
      const item = tutorialBenchmark().cases.find((item) => item.caseId === q.get("caseId"));
      const table = item?.page.tables.find((table) => table.version === q.get("version"));
      if (!item || !table?.record) return NextResponse.json({ error: "Unknown tutorial rubric." }, { status: 404 });
      return NextResponse.json({ record: table.record, source: item.page.source, version: table.version, status: table.status, errors: table.errors, ratings: table.ratings, fromCopy: false, notice: "Tutorial draft. Edits are for practice only.", canSave: false, cannotSaveReason: "Tutorial edits cannot be saved as a reviewed project rubric. Create your own project to save a rubric.", sourceSha256: table.sha256, replacesSha256: null });
    } catch (error) {
      return failure(error);
    }
  }
  try {
    return NextResponse.json(loadEditorPayload(projectsRoot(), q.get("caseset") ?? "", q.get("caseId") ?? "", q.get("version") ?? "", q.get("reviewer") ?? "", q.get("original") === "1"));
  } catch (error) {
    return failure(error);
  }
}

interface SaveBody { caseset: string; caseId: string; version: string; reviewer: string; record: AnswerTableCase | TextV2Case; timing: AuthoringTiming; sourceSha256: string; replacesSha256: string | null }

export async function PUT(request: NextRequest): Promise<NextResponse> {
  const site = new URL(requestOrigin(request));
  const origin = request.headers.get("origin");
  if (origin && origin !== site.origin) {
    return NextResponse.json({ error: "Rubric saves must come from this site." }, { status: 403 });
  }
  try {
    const body = (await request.json()) as SaveBody;
    if (body?.caseset === TUTORIAL_PROJECT) return NextResponse.json({ error: "Tutorial edits are for practice only and cannot be saved as a reviewed project rubric." }, { status: 400 });
    const sha256 = /^[0-9a-f]{64}$/;
    if (!body || typeof body.sourceSha256 !== "string" || !sha256.test(body.sourceSha256) ||
        !(body.replacesSha256 === null || typeof body.replacesSha256 === "string" && sha256.test(body.replacesSha256))) {
      return NextResponse.json({ error: "Saving requires the source and replacement identities loaded by the editor. Reload before saving." }, { status: 400 });
    }
    const root = projectsRoot();
    const result = saveReviewedTable({
      root: root, caseset: body.caseset, caseId: body.caseId, version: body.version, reviewer: body.reviewer, record: body.record, timing: body.timing,
      sourceSha256: body.sourceSha256, replacesSha256: body.replacesSha256,
    });

    return NextResponse.json(result);
  } catch (error) {
    return failure(error);
  }
}

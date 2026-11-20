import { existsSync, readFileSync } from "node:fs";
import { requestOrigin } from "@/lib/request-origin";
import { projectFailureStatus } from "@/lib/project-files";
import { NextRequest, NextResponse } from "next/server";

import { httpStatus, ValidationError } from "@/lib/caseset/editor";
import { BASE_NOT_ON_RECORD, reviewItems } from "@/lib/caseset/judgment-review";
import {
  baseReading, currentJudgment, DraftConflictError, finishReview, loadReviewState, saveDraft,
  type DraftInput, type ReviewTarget,
} from "@/lib/caseset/judgment-review-store";
import { casesetDir, inside, projectsRoot } from "@/lib/caseset/paths";
import { isTutorialProject } from "@/lib/onboarding";
import { TUTORIAL_PROJECT } from "@/lib/uti-tutorial-benchmark";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// The store reports a missing frozen base as a plain Error, so it is matched on the shared message.
function failure(error: unknown): NextResponse {
  const message = (error as Error).message;
  if (error instanceof DraftConflictError) return NextResponse.json({ error: message, draft: error.draft }, { status: 409 });
  if (error instanceof ValidationError) return NextResponse.json({ error: message, errors: error.errors }, { status: httpStatus(error) });
  return NextResponse.json({ error: message }, { status: message === BASE_NOT_ON_RECORD ? 409 : projectFailureStatus(error, httpStatus(error)) });
}

function parseTarget(root: string, value: unknown): ReviewTarget {
  const t = value as Partial<ReviewTarget> | null;
  if (!t || typeof t.caseset !== "string" || typeof t.model !== "string" || typeof t.id !== "string" || typeof t.trial !== "number") {
    throw new TypeError("A review target needs caseset, model, id and trial.");
  }
  if (!Number.isInteger(t.trial) || t.trial < 1) throw new TypeError("The trial must be a positive whole number.");
  return { root, caseset: t.caseset, model: t.model, id: t.id, trial: t.trial };
}

function refuseReadOnly(root: string, caseset: string): void {
  if (caseset === TUTORIAL_PROJECT || isTutorialProject(caseset)) throw new TypeError("The tutorial is read-only. Create your own project to review judgments.");
  if (caseset !== "demo") return;
  const file = inside(casesetDir(root, caseset), "provenance.json");
  const provenance = existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) as { synthetic?: boolean } : {};
  if (provenance.synthetic === true) throw new TypeError("The prepared demo is read-only. Create your own project before reviewing judgments.");
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const q = request.nextUrl.searchParams;
  try {
    const root = projectsRoot();
    const target = parseTarget(root, { caseset: q.get("caseset") ?? "", model: q.get("model") ?? "", id: q.get("id") ?? "", trial: Number(q.get("trial")) });
    const state = loadReviewState(target, q.get("reviewer") ?? "");
    const base = baseReading(target, state.draft);
    const judged = currentJudgment(target)!;
    return NextResponse.json({
      ...state, account: "local", basedOn: base.basedOn, basedOnReadingSha256: base.readingSha256, judgmentSha256: base.judgmentSha256,
      response: judged.response, items: reviewItems(base.reading, judged.rubric),
    }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return failure(error);
  }
}

async function mutate<T, R>(request: NextRequest, run: (body: Record<string, unknown>, root: string) => T, respond: (result: T) => R): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(requestOrigin(request)).origin) return NextResponse.json({ error: "Judgment reviews must come from this site." }, { status: 403 });
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const caseset = (body?.target as { caseset?: unknown } | undefined)?.caseset;
    if (typeof caseset !== "string") throw new TypeError("A review target needs caseset, model, id and trial.");
    const root = projectsRoot();
    refuseReadOnly(root, caseset);
    return NextResponse.json(respond(run(body, root)));
  } catch (error) {
    return failure(error);
  }
}

export async function PUT(request: NextRequest): Promise<NextResponse> {
  return mutate(request, (body, root) => {
    const d = body.draft as Partial<DraftInput> | undefined;
    if (!d || typeof d !== "object") throw new TypeError("A save needs a draft.");
    const replaces = body.replacesRevision;
    if (replaces !== null && !Number.isInteger(replaces)) throw new TypeError("A save needs replacesRevision, a revision number or null.");
    const draft = { draftId: d.draftId, reviewer: d.reviewer, judgmentSha256: d.judgmentSha256, basedOn: d.basedOn, basedOnReadingSha256: d.basedOnReadingSha256, verdicts: d.verdicts, evidence: d.evidence } as DraftInput;
    return saveDraft(parseTarget(root, body.target), draft, replaces as number | null);
  }, (result) => result);
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  return mutate(request, (body, root) => {
    if (typeof body.reviewer !== "string" || typeof body.draftId !== "string" || !Number.isInteger(body.draftRevision)) {
      throw new TypeError("Finishing needs reviewer, draftId and draftRevision.");
    }
    return finishReview(parseTarget(root, body.target), body.reviewer, body.draftId, body.draftRevision as number);
  }, (result) => ({ ...result, rescore: "local" }));
}

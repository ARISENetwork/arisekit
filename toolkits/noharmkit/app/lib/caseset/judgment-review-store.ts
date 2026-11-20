import { randomUUID } from "node:crypto";
import { closeSync, constants, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";

import { isValidReviewerId } from "@/lib/clinician-review";
import type { TextV2Case } from "@/lib/rubric-text-v2";
import type { TextV2Judgment } from "@/lib/text-v2-results";
import { ConflictError, ValidationError } from "@/lib/caseset/editor";
import { tableSha256 } from "@/lib/caseset/hash";
import { BINDING_KEYS, latestCurrentLine, type Bindings } from "@/lib/caseset/judgment-review-lines";
import { applyVerdicts, BASE_NOT_ON_RECORD, JUDGMENT_CHANGED, JUDGMENT_NOT_CURRENT, REVIEW_ALREADY_FINISHED, reviewItems, verdictErrors, type Verdict } from "@/lib/caseset/judgment-review";
import { sanitizeModel, versionState } from "@/lib/caseset/metrics";
import { assertModel, casesetDir, inside, list, NotFoundError } from "@/lib/caseset/paths";
import { loadLens, readJsonl, sharedRubric } from "@/lib/caseset/read";
import { appendReview, assertReviewWritable, autogradingItem, readReviews } from "@/lib/caseset/reviews";
import type { Item } from "@/lib/caseset/types";

type BasedOn = "judge" | "severe review";

export interface ReviewDraft {
  draftId: string;
  revision: number;
  reviewer: string;
  judgmentSha256: string;
  basedOn: BasedOn;
  basedOnReadingSha256: string;
  // Captured by the server from the judge record named by judgmentSha256; a caller never supplies them.
  bindings: Bindings;
  verdicts: Record<string, Verdict>;
  evidence: Record<string, string>;
  updatedAt: string;
}

export type DraftInput = Omit<ReviewDraft, "revision" | "updatedAt" | "bindings">;

export interface ReviewTarget { root: string; caseset: string; model: string; id: string; trial: number }

export interface FinishedReview extends Bindings {
  id: string;
  trial: number;
  caseId: string;
  model: string;
  judgment_sha256: string;
  basedOn: BasedOn;
  basedOnReadingSha256: string;
  reviewer: string;
  reviewedAt: string;
  rubricReviewed: boolean;
  verdicts: Record<string, Record<string, Verdict>>;
  evidence: Record<string, string>;
  reading: TextV2Judgment;
  readingSha256: string;
  draftId: string;
  draftRevision: number;
  status: "finished";
}

// A same-reviewer save or finish raced another tab. The stored draft goes back so the reviewer can choose.
export class DraftConflictError extends ConflictError {
  draft: ReviewDraft | null;

  constructor(message: string, draft: ReviewDraft | null) {
    super(message);
    this.draft = draft;
  }
}

const REVIEW_DIR = "judge-reviews";
const DRAFT_RACED = "This review was saved from another tab since this tab last saved.";
const SHA256 = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ITEM_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const VERDICTS: readonly string[] = ["complete", "partial", "notAddressed"];

export interface Judged { caseId: string; response: string; rubric: TextV2Case; judgmentSha256: string; reading: TextV2Judgment; bindings: Bindings }

interface SevereReceipt { id?: string; trial?: number; judgment_sha256?: string; status?: string; review?: TextV2Judgment | null }

function checkReviewer(reviewer: string): void {
  if (!isValidReviewerId(reviewer)) throw new Error("Invalid reviewer ID.");
}

function projectDir(target: ReviewTarget): string {
  const dir = casesetDir(target.root, target.caseset);
  assertModel(dir, target.model);
  if (!Number.isInteger(target.trial) || target.trial < 1) throw new NotFoundError(`no trial ${String(target.trial)}`);
  if (!ITEM_ID.test(target.id) || !readJsonl<Item>(inside(dir, "items.jsonl")).some((i) => i.id === target.id)) throw new NotFoundError(`no item ${target.id}`);
  return dir;
}

// Fresh reads only: these files change within one request.
function readLines<T>(file: string): T[] {
  if (!regularFile(file)) return [];
  return readFileSync(file, "utf8").split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line) as T);
}

// The judge record for the pair, only while it is current: same response, case presentation and rubric text.
export function currentJudgment(target: ReviewTarget): Judged | null {
  const { page, row } = loadLens(target.root, target.caseset, target.id, target.model, String(target.trial));
  const record = row.record;
  if (row.judge !== "pass" || !record?.textV2 || record.judge_protocol !== "J2.3" || row.response === null) return null;
  const { response_sha256, case_presentation_sha256, rubric_text_sha256 } = record;
  if (!response_sha256 || !case_presentation_sha256 || !rubric_text_sha256) return null;
  const label = sharedRubric(page.tables, page.provenance, page.caseId).label;
  const rubric = page.tables.find((t) => t.version === label)?.textV2;
  if (!rubric) return null;
  return {
    caseId: page.caseId, response: row.response, rubric, judgmentSha256: tableSha256(record.textV2), reading: record.textV2,
    bindings: { response_sha256, case_presentation_sha256, rubric_text_sha256 },
  };
}

function severeReviews(dir: string, target: ReviewTarget, judgmentSha256: string): TextV2Judgment[] {
  const file = inside(dir, "results", "severe-review", `${sanitizeModel(target.model)}.jsonl`);
  return readLines<SevereReceipt>(file).flatMap((r) => r.status === "pass" && r.review && r.id === target.id
    && (r.trial ?? 1) === target.trial && r.judgment_sha256 === judgmentSha256 ? [r.review] : []);
}

// Looks only in the source the base names: a severe review that changed nothing has the judge reading's hash.
function findBase(dir: string, target: ReviewTarget, judged: Judged | null, basedOn: BasedOn, judgmentSha256: string, readingSha256: string): TextV2Judgment | null {
  if (basedOn === "judge") return judged && judged.judgmentSha256 === judgmentSha256 && readingSha256 === judgmentSha256 ? judged.reading : null;
  return severeReviews(dir, target, judgmentSha256).findLast((r) => tableSha256(r) === readingSha256) ?? null;
}

// A current saved draft keeps the reading it started from, so reopening it never rebases it onto a newer severe review.
export function baseReading(target: ReviewTarget, draft: ReviewDraft | null = null): { judgmentSha256: string; basedOn: BasedOn; reading: TextV2Judgment; readingSha256: string; bindings: Bindings } {
  const dir = projectDir(target);
  const judged = currentJudgment(target);
  if (!judged) throw new ConflictError(JUDGMENT_NOT_CURRENT);
  const kept = draft && !outOfDate(draft, judged) ? findBase(dir, target, judged, draft.basedOn, draft.judgmentSha256, draft.basedOnReadingSha256) : null;
  if (draft && kept) return { judgmentSha256: judged.judgmentSha256, basedOn: draft.basedOn, reading: kept, readingSha256: tableSha256(kept), bindings: judged.bindings };
  const severe = severeReviews(dir, target, judged.judgmentSha256).at(-1);
  const [reading, basedOn]: [TextV2Judgment, BasedOn] = severe ? [severe, "severe review"] : [judged.reading, "judge"];
  return { judgmentSha256: judged.judgmentSha256, basedOn, reading, readingSha256: tableSha256(reading), bindings: judged.bindings };
}

export function readingByHash(target: ReviewTarget, judgmentSha256: string, readingSha256: string): TextV2Judgment | null {
  const dir = projectDir(target);
  const judged = currentJudgment(target);
  return findBase(dir, target, judged, "judge", judgmentSha256, readingSha256) ?? findBase(dir, target, judged, "severe review", judgmentSha256, readingSha256);
}

// Folders resolve through the containment check; files keep their literal path so a planted link is refused, not followed.
const reviewsFile = (dir: string, model: string): string => path.join(inside(dir, "results", REVIEW_DIR), `${sanitizeModel(model)}.jsonl`);
const draftsFolder = (dir: string, model: string): string => inside(dir, "results", REVIEW_DIR, "drafts", sanitizeModel(model));
const draftPath = (dir: string, target: ReviewTarget, reviewer: string): string =>
  path.join(draftsFolder(dir, target.model), `${target.id}.${target.trial}.${reviewer}.json`);

function regularFile(file: string): boolean {
  const entry = lstatSync(file, { throwIfNoEntry: false });
  if (entry && !entry.isFile()) throw new NotFoundError(`${path.basename(file)} is not a regular file`);
  return Boolean(entry);
}

function readDraft(dir: string, target: ReviewTarget, reviewer: string): ReviewDraft | null {
  const file = draftPath(dir, target, reviewer);
  return regularFile(file) ? JSON.parse(readFileSync(file, "utf8")) as ReviewDraft : null;
}

function removeDraft(dir: string, target: ReviewTarget, reviewer: string): void {
  const file = draftPath(dir, target, reviewer);
  if (regularFile(file)) unlinkSync(file);
}

// A stored draft is out of date once the judge record it names, or any binding it captured, is no longer current.
function outOfDate(draft: ReviewDraft, judged: Judged | null): boolean {
  return !judged || draft.judgmentSha256 !== judged.judgmentSha256 || BINDING_KEYS.some((key) => draft.bindings?.[key] !== judged.bindings[key]);
}

// The replaced draft is kept, never deleted. Exclusive create neither follows nor overwrites an existing entry; a
// byte-identical copy left by an earlier attempt whose draft write failed counts as done.
function supersede(dir: string, target: ReviewTarget, stored: ReviewDraft): void {
  if (!UUID.test(stored.draftId)) throw new Error("The stored draft has no UUID draftId.");
  const folder = inside(dir, "results", REVIEW_DIR, "drafts", "superseded", sanitizeModel(target.model));
  mkdirSync(folder, { recursive: true });
  const file = path.join(folder, `${target.id}.${target.trial}.${stored.reviewer}.${stored.draftId}.json`);
  const bytes = readFileSync(draftPath(dir, target, stored.reviewer));
  if (regularFile(file) && readFileSync(file).equals(bytes)) return;
  writeFileSync(file, bytes, { flag: "wx" });
}

function finished(dir: string, target: ReviewTarget, judged: Judged | null): FinishedReview | null {
  if (!judged) return null;
  return latestCurrentLine(readLines<FinishedReview>(reviewsFile(dir, target.model)), target.id, target.trial, judged.judgmentSha256, judged.bindings);
}

export function loadReviewState(target: ReviewTarget, reviewer: string): { draft: ReviewDraft | null; draftOutOfDate: boolean; othersInProgress: string[]; finished: FinishedReview | null } {
  checkReviewer(reviewer);
  const dir = projectDir(target);
  const prefix = `${target.id}.${target.trial}.`;
  const othersInProgress = list(dir, "results", REVIEW_DIR, "drafts", sanitizeModel(target.model))
    .filter((name) => name.startsWith(prefix) && name.endsWith(".json"))
    .map((name) => name.slice(prefix.length, -".json".length))
    .filter((name) => isValidReviewerId(name) && name !== reviewer)
    .sort();
  const draft = readDraft(dir, target, reviewer);
  const judged = currentJudgment(target);
  return { draft, draftOutOfDate: draft !== null && outOfDate(draft, judged), othersInProgress, finished: finished(dir, target, judged) };
}

function checkDraft(draft: DraftInput): void {
  checkReviewer(draft.reviewer);
  if (typeof draft.draftId !== "string" || !UUID.test(draft.draftId)) throw new Error("A draft needs a UUID draftId.");
  if (!SHA256.test(draft.judgmentSha256) || !SHA256.test(draft.basedOnReadingSha256)) throw new Error("A draft must record the judgment and base reading sha256.");
  if (draft.basedOn !== "judge" && draft.basedOn !== "severe review") throw new Error("A draft must be based on the judge or a severe review.");
  const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
  if (!record(draft.verdicts) || Object.values(draft.verdicts).some((v) => !VERDICTS.includes(v))) throw new Error("Verdicts must be complete, partial or notAddressed.");
  if (!record(draft.evidence) || Object.values(draft.evidence).some((v) => typeof v !== "string")) throw new Error("Evidence must be text.");
}

function finishedLines(dir: string, target: ReviewTarget, reviewer: string, draftId: string): FinishedReview[] {
  return readLines<FinishedReview>(reviewsFile(dir, target.model)).filter((line) => line.draftId === draftId
    && line.reviewer === reviewer && line.id === target.id && line.trial === target.trial);
}

export function saveDraft(target: ReviewTarget, draft: DraftInput, replacesRevision: number | null, now?: Date): { revision: number; updatedAt: string } {
  checkDraft(draft);
  const dir = projectDir(target);
  // A finished draftId is closed: saving under it again would let a finish retry delete the new verdicts.
  if (finishedLines(dir, target, draft.reviewer, draft.draftId).length) throw new ConflictError(REVIEW_ALREADY_FINISHED);
  const stored = readDraft(dir, target, draft.reviewer);
  // A new draftId may replace the stored draft, naming its revision, only once that draft is out of date.
  const replacing = stored !== null && draft.draftId !== stored.draftId && replacesRevision === stored.revision && outOfDate(stored, currentJudgment(target));
  const expected = stored ? { draftId: stored.draftId, revision: stored.revision } : null;
  if (!replacing && (replacesRevision === null ? expected !== null : expected?.draftId !== draft.draftId || expected.revision !== replacesRevision)) {
    throw new DraftConflictError(DRAFT_RACED, stored);
  }
  const bindings = !replacing && stored && stored.judgmentSha256 === draft.judgmentSha256 && stored.bindings ? stored.bindings : judgeBindings(target, draft.judgmentSha256);
  const updatedAt = (now ?? new Date()).toISOString();
  const revision = (replacing ? 0 : stored?.revision ?? 0) + 1;
  const body: ReviewDraft = {
    draftId: draft.draftId, revision, reviewer: draft.reviewer, judgmentSha256: draft.judgmentSha256, basedOn: draft.basedOn,
    basedOnReadingSha256: draft.basedOnReadingSha256, bindings, verdicts: draft.verdicts, evidence: draft.evidence, updatedAt,
  };
  mkdirSync(draftsFolder(dir, target.model), { recursive: true });
  const file = draftPath(dir, target, draft.reviewer);
  regularFile(file);
  if (replacing) supersede(dir, target, stored);
  const temporary = `${file}.${randomUUID()}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(body, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  renameSync(temporary, file);
  return { revision, updatedAt };
}

// Bindings of the judge record the draft names, read when the draft starts on it. Later saves carry them unchanged.
function judgeBindings(target: ReviewTarget, judgmentSha256: string): Bindings {
  const current = baseReading(target);
  if (current.judgmentSha256 !== judgmentSha256) throw new ConflictError(JUDGMENT_CHANGED);
  return current.bindings;
}

function appendLine(dir: string, model: string, line: FinishedReview): void {
  mkdirSync(inside(dir, "results", REVIEW_DIR), { recursive: true });
  const file = reviewsFile(dir, model);
  regularFile(file);
  // Open without following a link planted after the check. One line is appended; history is never rewritten.
  const descriptor = openSync(file, constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | constants.O_NOFOLLOW, 0o666);
  try {
    writeFileSync(descriptor, `${JSON.stringify(line)}\n`, "utf8");
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function recordReview(dir: string, line: FinishedReview): void {
  const item = autogradingItem(line.id, line.model, line.trial);
  const recorded = readReviews(dir).some((r) => r.step === "autograding" && r.caseId === line.caseId && r.item === item
    && r.contentSha256 === line.readingSha256 && r.reviewer === line.reviewer && r.reviewedAt === line.reviewedAt);
  if (recorded) return;
  appendReview(dir, {
    step: "autograding", caseId: line.caseId, item, contentSha256: line.readingSha256, basedOnSha256: line.judgment_sha256,
    reviewer: line.reviewer, reviewedAt: line.reviewedAt,
  });
}

// The case's shared rubric review state as the project records it now; the browser's view of it is never trusted.
function sharedRubricReviewed(dir: string, target: ReviewTarget): boolean {
  const { page } = loadLens(target.root, target.caseset, target.id, target.model, String(target.trial));
  const label = sharedRubric(page.tables, page.provenance, page.caseId).label;
  const table = page.tables.find((t) => t.version === label);
  return table !== undefined && versionState(table, page.caseId, readReviews(dir)) === "reviewed";
}

export function finishReview(target: ReviewTarget, reviewer: string, draftId: string, draftRevision: number, now?: Date): { reviewedAt: string; readingSha256: string } {
  checkReviewer(reviewer);
  const dir = projectDir(target);
  // A retry after a partial finish completes it instead of appending a second line.
  const done = finishedLines(dir, target, reviewer, draftId).find((line) => line.draftRevision === draftRevision);
  if (done) {
    recordReview(dir, done);
    const left = readDraft(dir, target, reviewer);
    if (left?.draftId === draftId && left.revision === draftRevision) removeDraft(dir, target, reviewer);
    return { reviewedAt: done.reviewedAt, readingSha256: done.readingSha256 };
  }

  const draft = readDraft(dir, target, reviewer);
  if (!draft || draft.draftId !== draftId || draft.revision !== draftRevision) throw new DraftConflictError(DRAFT_RACED, draft);
  const judged = currentJudgment(target);
  if (!judged || outOfDate(draft, judged)) throw new ConflictError(JUDGMENT_CHANGED);
  const base = findBase(dir, target, judged, draft.basedOn, draft.judgmentSha256, draft.basedOnReadingSha256);
  if (!base) throw new Error(BASE_NOT_ON_RECORD);
  const items = reviewItems(base, judged.rubric);
  const errors = verdictErrors(items, draft.verdicts, draft.evidence, judged.response);
  if (errors.length) throw new ValidationError(errors);
  const reading = applyVerdicts(base, items, draft.verdicts, draft.evidence);

  const verdicts: Record<string, Record<string, Verdict>> = {};
  const evidence: Record<string, string> = {};
  for (const item of items) {
    (verdicts[item.criterionId] ??= {})[item.rowId] = draft.verdicts[item.key];
    const added = reading.decisions[item.criterionId].recommended.find((m) => m.rowId === item.rowId);
    if (added && !item.judgeMatch?.evidence.trim()) evidence[item.key] = added.evidence;
  }
  const line: FinishedReview = {
    id: target.id, trial: target.trial, caseId: judged.caseId, model: target.model, judgment_sha256: judged.judgmentSha256,
    basedOn: draft.basedOn, basedOnReadingSha256: draft.basedOnReadingSha256, ...judged.bindings, reviewer,
    reviewedAt: (now ?? new Date()).toISOString(), rubricReviewed: sharedRubricReviewed(dir, target), verdicts, evidence, reading, readingSha256: tableSha256(reading),
    draftId, draftRevision, status: "finished",
  };
  assertReviewWritable(dir);
  appendLine(dir, target.model, line);
  recordReview(dir, line);
  removeDraft(dir, target, reviewer);
  return { reviewedAt: line.reviewedAt, readingSha256: line.readingSha256 };
}

import { randomUUID } from "node:crypto";
import { existsSync, lstatSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";

import { isTextV2, type TextV2Case } from "@/lib/rubric-text-v2";
import { textV2Sha256 } from "@/lib/text-v2-hash";
import { textV2ScoringErrors, validateTextV2ForProject, withoutDecisionRefs } from "@/lib/text-v2-eligibility";
import { validateAnswerTable } from "@/lib/answer-table";
import type { AnswerTableCase, AuthoringTiming } from "@/lib/answer-table";
import { isValidReviewerId } from "@/lib/clinician-review";
import { assertCase, casesetDir, inside, listVersionLabels, NotFoundError } from "@/lib/caseset/paths";
import { tableSha256, textSha256 } from "@/lib/caseset/hash";
import { loadTableVersion, readJson } from "@/lib/caseset/read";
import { appendReview, assertReviewWritable } from "@/lib/caseset/reviews";
import type { CommitteeRatings, ReviewedFile } from "@/lib/caseset/types";
import type { CaseSource } from "@/lib/types";

type EditableRubric = AnswerTableCase | TextV2Case;
const identity = (record: EditableRubric): string => isTextV2(record) ? textV2Sha256(record) : tableSha256(record);

export class ValidationError extends Error {
  errors: string[];

  constructor(errors: string[]) {
    super(errors.join(" "));
    this.errors = errors;
  }
}

// The disk changed after the reviewer opened the page: saving would record a basis they never saw.
export class ConflictError extends Error {}

// Our own checks throw NotFoundError, ValidationError, or a plain Error (bad request). Anything carrying a Node
// errno `code` (permission denied, disk full) is a server fault, not the caller's.
export function httpStatus(error: unknown): 400 | 404 | 409 | 422 | 500 {
  if (error instanceof NotFoundError) return 404;
  if (error instanceof ConflictError) return 409;
  if (error instanceof ValidationError) return 422;
  return typeof (error as { code?: unknown } | null)?.code === "string" ? 500 : 400;
}

function checkReviewer(reviewer: string): void {
  if (!isValidReviewerId(reviewer)) throw new Error("Invalid reviewer ID.");
}

function realDirectory(folder: string, label: string): void {
  const entry = lstatSync(folder, { throwIfNoEntry: false });
  if (entry && !entry.isDirectory()) throw new NotFoundError(`${label} is not a real directory`);
  if (!entry) mkdirSync(folder);
}

// Preserve the prior files verbatim, independently of their JSON format. History is never overwritten.
// Stage every replacement before renaming any current file; each rename is atomic, not the whole save.
function writeAll(dir: string, stem: string, files: Array<[string, unknown]>): void {
  const tables = path.join(inside(dir), "answer-tables");
  const folder = lstatSync(tables, { throwIfNoEntry: false });
  if (!folder?.isDirectory()) throw new NotFoundError("answer-tables is not a real directory");
  const snapshot = randomUUID();
  const planned = files.map(([name, body]) => ({ name, target: path.join(tables, name), temporary: path.join(tables, `${name}.${snapshot}.tmp`), bytes: `${JSON.stringify(body, null, 2)}\n` }));
  for (const { name, target, temporary } of planned) {
    for (const [file, label] of [[target, name], [path.join(tables, `${name}.tmp`), `${name}.tmp`], [temporary, path.basename(temporary)]] as const) {
      const entry = lstatSync(file, { throwIfNoEntry: false });
      if (entry && !entry.isFile()) throw new NotFoundError(`${label} is not a regular file`);
    }
  }
  const previous = planned.filter(({ target }) => lstatSync(target, { throwIfNoEntry: false })).map(({ name, target }) => ({ name, bytes: readFileSync(target) }));
  if (previous.length) {
    const history = path.join(tables, "history");
    realDirectory(history, "answer-tables/history");
    const artifact = path.join(history, stem);
    realDirectory(artifact, `history/${stem}`);
    const destination = path.join(artifact, snapshot);
    // A collision refuses rather than reusing an existing snapshot, including any planted symlink.
    mkdirSync(destination);
    for (const { name, bytes } of previous) writeFileSync(path.join(destination, name), bytes, { flag: "wx" });
  }
  for (const { temporary, bytes } of planned) writeFileSync(temporary, bytes, { encoding: "utf8", flag: "wx" });
  for (const { target, temporary } of planned) renameSync(temporary, target);
}

export interface EditorPayload {
  record: EditableRubric;
  source: CaseSource;
  version: string;
  status: "pass" | "failed";
  errors: string[];
  ratings: CommitteeRatings | null;
  fromCopy: boolean;
  notice: string;
  canSave?: boolean;
  cannotSaveReason?: string;
  timing?: AuthoringTiming;
  savedAt?: string;
  sourceSha256: string | null;
  replacesSha256: string | null;
}

// original: the editor's Reset. Your reviewed copy comes back with the rubric it was based on, keeping the copy's
// hashes so the next save replaces it; any other version is already the original.
export function loadEditorPayload(root: string, caseset: string, caseId: string, version: string, reviewer: string, original = false): EditorPayload {
  checkReviewer(reviewer);
  const dir = casesetDir(root, caseset);
  assertCase(dir, caseId);
  const table = loadTableVersion(dir, caseId, version);
  const payload = editorPayload(dir, caseId, version, reviewer, table);
  if (!original || !payload.fromCopy) return payload;
  if (!table.basedOn) throw new Error(`${version} has no recorded original to reset to.`);
  const basis = loadTableVersion(dir, caseId, table.basedOn.version);
  const record = basis.textV2 ?? basis.record;
  if (!record) throw new Error(`${table.basedOn.version} has no rubric to reset to.`);
  return { ...payload, record };
}

function editorPayload(dir: string, caseId: string, version: string, reviewer: string, table: ReturnType<typeof loadTableVersion>): EditorPayload {
  const record = table.textV2 ?? table.record;
  if (!record) throw new Error(`${version} has no rubric to open; its errors are on the Rubrics page.`);
  const own = `reviewed-${reviewer}`;
  const fromCopy = version === own;
  const notice = fromCopy
    ? `Your reviewed copy, based on ${table.basedOn?.version ?? "an unrecorded version"}`
    : listVersionLabels(dir, caseId).includes(own)
      ? `Opened ${version}. Saving replaces your reviewed copy (${own}).`
      : `Opened ${version}. Saving creates ${own}; ${version} is not changed.`;
  // Re-saving your own copy keeps its stored basis, so only other versions need a hash.
  const basis = fromCopy && table.basedOn ? { sha256: "own copy" } : basisHash(record, table.sha256);
  const ownExists = listVersionLabels(dir, caseId).includes(own);
  const replacesSha256 = !fromCopy && ownExists ? hashOrNull(loadTableVersion(dir, caseId, own).textV2 ?? loadTableVersion(dir, caseId, own).record) : null;
  const sourceSha256 = fromCopy ? hashOrNull(record) : "error" in basis ? null : basis.sha256;
  return {
    record,
    source: readJson<CaseSource>(inside(dir, "cases", `${caseId}.json`)),
    version,
    status: table.status,
    errors: table.errors,
    ratings: table.ratings,
    fromCopy,
    notice,
    canSave: !("error" in basis),
    sourceSha256,
    replacesSha256,
    ...("error" in basis ? { cannotSaveReason: `This version cannot be the basis of a reviewed copy: ${basis.error}. Open another version.` } : {}),
    ...(fromCopy ? { timing: table.timing, savedAt: table.savedAt } : {}),
  };
}

// A failed version carries no hash. It can still be the basis when it hashes; one holding a value outside the
// hash's domain (a score of 7.5) cannot record what a copy was based on. The editor learns this at load time, so
// the clinician is never invited to fix a table that can never be saved from.
function basisHash(record: EditableRubric, known: string | null): { sha256: string } | { error: string } {
  if (known) return { sha256: known };
  try {
    return { sha256: identity(record) };
  } catch (error) {
    return { error: (error as Error).message };
  }
}

// Invalid own copies can still be repaired: use their exact JSON identity for conflict checks only.
function hashOrNull(record: EditableRubric | null): string | null {
  if (!record) return null;
  try {
    return identity(record);
  } catch {
    return textSha256(JSON.stringify(record));
  }
}

function basisSha256(version: string, record: EditableRubric, known: string | null): string {
  const basis = basisHash(record, known);
  if ("error" in basis) throw new ValidationError([`${version} cannot be the basis of a reviewed copy: ${basis.error}. Open another version.`]);
  return basis.sha256;
}

export interface SaveRequest {
  root: string;
  caseset: string;
  caseId: string;
  version: string;
  reviewer: string;
  record: EditableRubric;
  timing: AuthoringTiming;
  now?: Date;
  // Sent by the editor: the hashes it loaded. Absent in direct callers, which skip the conflict check.
  sourceSha256?: string;
  replacesSha256?: string | null;
}

// The viewer's only write. Generated runs are read, never written.
export function saveReviewedTable(req: SaveRequest): { savedAt: string; version: string; contentSha256: string } {
  checkReviewer(req.reviewer);
  const dir = casesetDir(req.root, req.caseset);
  assertCase(dir, req.caseId);
  if (req.record?.caseId !== req.caseId) throw new Error("Record item ID does not match.");
  const basis = loadTableVersion(dir, req.caseId, req.version);
  const sourceRecord = basis.textV2 ?? basis.record;
  if (!sourceRecord) throw new Error(`${req.version} has no rubric to base a review on.`);
  if (isTextV2(sourceRecord) !== isTextV2(req.record)) throw new ValidationError(["A reviewed copy must keep its source rubric format."]);
  const provenancePath = inside(dir, "provenance.json");
  const provenance = existsSync(provenancePath) ? readJson<Record<string, unknown>>(provenancePath) : {};
  const errors = isTextV2(req.record) ? validateTextV2ForProject(req.record, "draft", provenance).errors : validateAnswerTable(req.record);
  if (errors.length) throw new ValidationError(errors.map(withoutDecisionRefs));
  const version = `reviewed-${req.reviewer}`;
  if (req.sourceSha256 !== undefined) {
    const current = hashOrNull(sourceRecord);
    if (current !== req.sourceSha256) throw new ConflictError(`${req.version} changed since you opened it. Reload the page to review the current version.`);
  }
  if (req.replacesSha256 !== undefined && req.version !== version) {
    const exists = listVersionLabels(dir, req.caseId).includes(version);
    const current = exists ? hashOrNull(loadTableVersion(dir, req.caseId, version).textV2 ?? loadTableVersion(dir, req.caseId, version).record) : null;
    if (current !== req.replacesSha256) throw new ConflictError(`Your reviewed copy (${version}) changed since you opened this page. Reload before saving.`);
  }
  // Re-saving your own copy keeps the version it was first based on.
  const basedOn = basis.kind === "reviewed" && basis.reviewer === req.reviewer && basis.basedOn
    ? basis.basedOn
    : { version: req.version, sha256: basisSha256(req.version, sourceRecord, basis.sha256) };
  const savedAt = (req.now ?? new Date()).toISOString();
  const contentSha256 = identity(req.record);
  assertReviewWritable(dir);
  const file = { record: req.record, basedOn, reviewer: req.reviewer, timing: req.timing, savedAt };
  const scoringErrors = isTextV2(req.record) ? textV2ScoringErrors(req.record, provenance) : [];
  const warnings = isTextV2(req.record) ? validateTextV2ForProject(req.record, "draft", provenance).warnings : [];
  writeAll(dir, `${req.caseId}.${version}`, [[`${req.caseId}.${version}.json`, file], [`${req.caseId}.${version}.status.json`, { status: scoringErrors.length ? "draft" : "pass", errors: [], ...(isTextV2(req.record) ? { format: req.record.format, scorer: "S2", scoringErrors, warnings } : {}), savedAt }]]);
  appendReview(dir, { step: "rubrics", caseId: req.caseId, item: version, contentSha256, basedOnSha256: basedOn.sha256, reviewer: req.reviewer, reviewedAt: savedAt });
  return { savedAt, version, contentSha256 };
}

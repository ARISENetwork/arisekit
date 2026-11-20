import { AsyncLocalStorage } from "node:async_hooks";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { isTextV2 } from "@/lib/rubric-text-v2";
import { textV2ScoringErrors, validateTextV2ForProject, withoutDecisionRefs } from "@/lib/text-v2-eligibility";
import { textV2JudgeTextSha256, textV2Sha256 } from "@/lib/text-v2-hash";
import { textV2RuntimeCheck } from "@/lib/text-v2-runtime";
import type { TextV2Judgment, TextV2Score } from "@/lib/text-v2-results";
import type { AnswerTableCase } from "@/lib/answer-table";
import { tableSha256, textSha256 } from "@/lib/caseset/hash";
import { currentFinishedReview } from "@/lib/caseset/judgment-review-lines";
import { needsProvisionalBanner } from "@/lib/caseset/provisional";
import {
  assertCase, assertModel, assertVersion, caseIds, casesetDir, inside, KIT_ROOT,
  listCasesetNames, listModels, listVersionLabels, NotFoundError,
} from "@/lib/caseset/paths";
import type {
  CasePage, CasesetSummary, CommitteeRatings, Item, JudgeRecord, JudgeState, Lens, ResponseRecord,
  ResponseRow, ReviewedFile, ScoreCheck, ScoredRecord, StageCommands, TableVersion,
} from "@/lib/caseset/types";
import type { CaseSource } from "@/lib/types";
import { caseEdits, outdatedResponse, outdatedRubrics } from "@/lib/dataset-outdated";

const jsonlReads = new AsyncLocalStorage<Map<string, unknown[]>>();

// Share parsed model files across cases in one load, never across page requests.
export function withJsonlReadCache<T>(load: () => T): T {
  return jsonlReads.run(new Map(), load);
}

// Readers take only paths returned by inside().
export function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(file, "utf8")) as T;
}

export function readJsonl<T>(file: string): T[] {
  const cache = jsonlReads.getStore();
  const cached = cache?.get(file);
  if (cached) return cached as T[];
  if (!existsSync(file)) return [];
  const rows = readFileSync(file, "utf8").split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line) as T);
  cache?.set(file, rows);
  return rows;
}

function readItems(dir: string): Item[] {
  return readJsonl<Item>(inside(dir, "items.jsonl"));
}

const baseId = (item: Item): string => item.metadata?.base_id ?? item.id;

export function listCasesets(root: string): CasesetSummary[] {
  return listCasesetNames(root).map((name) => {
    const dir = inside(root, name);
    const ids = caseIds(dir);
    const provenance = inside(dir, "provenance.json");
    const provisional = ids.some((id) => needsProvisionalBanner(loadCasePage(root, name, id)));
    return {
      name,
      answerTable: ids.length > 0,
      cases: ids.length || new Set(readItems(dir).map(baseId)).size,
      updatedAt: existsSync(provenance) ? readJson<{ updated_at?: string }>(provenance).updated_at ?? null : null,
      clinicianReviewed: ids.length > 0 && ids.every((id) => listVersionLabels(dir, id).some((v) => v.startsWith("reviewed-") && readStatus(dir, id, v).status === "pass")),
      provisional,
    };
  });
}

interface StatusFile { status: "pass" | "failed" | "draft"; errors?: string[]; warnings?: string[]; provenance?: Record<string, unknown> }

// A missing status file reads as failed, so a version is never shown as passing without evidence.
function readStatus(dir: string, caseId: string, label: string): StatusFile {
  const file = inside(dir, "answer-tables", `${caseId}.${label}.status.json`);
  return existsSync(file) ? readJson<StatusFile>(file) : { status: "failed", errors: ["no status file"] };
}

// Only a passing table is hashed: a failed table can be anything (a score of 7.5 is outside the hash's
// domain), Python refuses to judge it, and nothing can be current against it.
const hashIfPass = (status: StatusFile, record: AnswerTableCase | null): string | null => (record && status.status === "pass" ? tableSha256(record) : null);

// Ratings describe one exact table: hide them for a failed table or when the table changed after they were made.
function currentRatings(ratings: CommitteeRatings | null, sha256: string | null): CommitteeRatings | null {
  return ratings && ratings.status !== "failed" && sha256 !== null && ratings.table_sha256 === sha256 ? ratings : null;
}

export function loadTableVersion(dir: string, caseId: string, label: string): TableVersion {
  assertCase(dir, caseId);
  const version = assertVersion(dir, caseId, label);
  const at = (suffix: string): string => inside(dir, "answer-tables", `${caseId}.${label}${suffix}`);
  const optional = <T>(file: string): T | null => (existsSync(file) ? readJson<T>(file) : null);
  const status = readStatus(dir, caseId, label);
  const stored = optional<unknown>(at(".json"));
  const native = version.kind === "reviewed" && stored && typeof stored === "object" && "record" in stored ? stored.record : stored;
  if (isTextV2(native)) {
    const provenance = optional<Record<string, unknown>>(inside(dir, "provenance.json")) ?? {};
    const draft = validateTextV2ForProject(native, "draft", provenance);
    const scoring = { errors: textV2ScoringErrors(native, provenance) };
    const valid = draft.errors.length === 0;
    const review = version.kind === "reviewed" ? stored as ReviewedFile : null;
    return {
      version: label, kind: version.kind, status: status.status === "pass" && !scoring.errors.length ? "pass" : "failed",
      errors: [...(status.errors ?? []), ...scoring.errors].map(withoutDecisionRefs), warnings: draft.warnings.map(withoutDecisionRefs), record: null,
      ...(valid ? { textV2: native } : {}), raw: valid ? null : JSON.stringify(native, null, 2),
      sha256: valid ? textV2Sha256(native) : null, ratings: null, provenance: status.provenance ?? null,
      ...(review ? { basedOn: review.basedOn, reviewer: review.reviewer, savedAt: review.savedAt, timing: review.timing } : {}),
    };
  }
  if (version.kind === "reviewed") {
    const file = readJson<ReviewedFile>(at(".json"));
    return {
      version: label, kind: "reviewed", status: status.status === "pass" ? "pass" : "failed", errors: status.errors ?? [], record: file.record, raw: null,
      sha256: hashIfPass(status, file.record), ratings: null, provenance: null,
      basedOn: file.basedOn, reviewer: file.reviewer, savedAt: file.savedAt, timing: file.timing,
    };
  }
  const record = optional<AnswerTableCase>(at(".json"));
  const sha256 = hashIfPass(status, record);
  return {
    version: label, kind: "run", status: status.status === "pass" ? "pass" : "failed", errors: status.errors ?? [], record,
    raw: existsSync(at(".raw.txt")) ? readFileSync(at(".raw.txt"), "utf8") : null,
    sha256,
    ratings: currentRatings(optional<CommitteeRatings>(at(".ratings.json")), sha256),
    provenance: status.provenance ?? null,
  };
}

export function disagreementCount(ratings: CommitteeRatings | null): number | null {
  if (!ratings) return null;
  return [ratings.usualCare, ...Object.values(ratings.decisions)].filter((item) => item?.disagreement).length;
}

export function responseError(r: ResponseRecord): string | null {
  return r.error ?? (r.response ? null : "empty response");
}

// The rubric a current-grading case is judged and scored against (pipeline_v2_slots.shared_label): the latest saved
// passing clinician review of the current case text, else the case's recorded base; when an edit to the case text
// put that base out of date, the newest passing rubric generated since. `tables` carry their out-of-date status.
export interface SharedRubric { label: string | null; textSha256: string | null }

export function sharedRubric(tables: TableVersion[], provenance: Record<string, unknown>, caseId: string): SharedRubric {
  const key = (t: TableVersion): [string, string] => [t.savedAt ?? "", t.version.slice("reviewed-".length)];
  const later = (a: TableVersion, b: TableVersion): boolean => {
    const [x, y] = [key(a), key(b)];
    return x[0] !== y[0] ? x[0] > y[0] : x[1] > y[1];
  };
  const current = (t: TableVersion): boolean => t.status === "pass" && Boolean(t.textV2) && !t.outdated;
  const reviews = tables.filter(t => t.kind === "reviewed" && current(t));
  const state = provenance.pipeline_v2 as { base_rubric?: unknown; case_base_rubrics?: Record<string, unknown> } | undefined;
  const recorded = state?.case_base_rubrics?.[caseId] ?? state?.base_rubric;
  const base = typeof recorded === "string" ? recorded : null;
  const runs = tables.filter(t => t.kind === "run" && current(t)).sort((a, b) => Number(b.version.slice(3)) - Number(a.version.slice(3)));
  const label = reviews.length ? reviews.reduce((a, b) => (later(b, a) ? b : a)).version
    : base && !tables.find(t => t.version === base)?.outdated ? base : base && runs.length ? runs[0].version : base;
  // An out-of-date label is kept for display, but it offers no usable text: judgments against it are stale.
  const table = tables.find(t => t.version === label && t.status === "pass" && t.textV2 && !t.outdated);
  return { label, textSha256: table?.textV2 ? textV2JudgeTextSha256(table.textV2) : null };
}

// A judgment is current only while its rubric, response, case identity, and question still match. A current-grading
// judgment binds only the judge-visible text of the case's shared rubric, so a ratings-only change keeps it.
export function judgeState(r: ResponseRecord, record: JudgeRecord | null, hashes: Map<string, string | null>, caseId: string, presentation: string, provenance: Record<string, unknown> = {}, shared: SharedRubric | null = null): JudgeState {
  if (responseError(r)) return "no response";
  if (!record) return "not run";
  if (record.status !== "pass") return "failed";
  if (record.caseId !== caseId) return "stale";
  if (record.judge_protocol === "J2.3") {
    if (!record.rubric_text_sha256) return "unverified";
    if (!shared?.textSha256 || record.rubric_text_sha256 !== shared.textSha256) return "stale";
  } else if (hashes.get(record.rubric) !== record.rubric_sha256) return "stale";
  if ((record.response_sha256 && record.response_sha256 !== textSha256(r.response!)) ||
      (record.case_presentation_sha256 && record.case_presentation_sha256 !== textSha256(presentation))) return "stale";
  if (!record.response_sha256 || !record.case_presentation_sha256) return "unverified";
  if (record.textV2) {
    const runtime = textV2RuntimeCheck(provenance, record);
    if (runtime !== "current") return runtime === "mismatch" ? "stale" : "unverified";
  }
  return "pass";
}

// A scored file can outlive its inputs. Match on the judgment and source identities, not only id and trial.
// A current-grading score is made against the case's shared rubric, whose label can differ from the judgment's: it is
// current while it names the shared rubric and that rubric's full hash (ratings included) is unchanged.
export function scoreCheck(scored: ScoredRecord | TextV2Score, record: JudgeRecord, hashes: Map<string, string | null> = new Map(), shared: SharedRubric | null = null): ScoreCheck {
  const slotted = "freeze" in scored && scored.freeze === "pipeline-v2";
  if (slotted) {
    if (scored.rubric !== shared?.label || scored.rubric_sha256 !== hashes.get(scored.rubric) || scored.rubric_text_sha256 !== record.rubric_text_sha256) return "mismatch";
  } else if (scored.rubric !== record.rubric) return "mismatch";
  if (!scored.rubric_sha256 || !scored.judgment_sha256 || !scored.response_sha256 || !scored.case_presentation_sha256) return "unverified";
  if ("scorer" in scored && scored.scorer === "S2") {
    const keys = ["judge_scoring_source_commit", "judge_protocol", "judge_contract_sha256"] as const;
    if (keys.some(key => record[key] !== undefined)) {
      if (keys.some(key => !scored[key])) return "unverified";
      if (keys.some(key => scored[key] !== record[key]) || scored.judge !== record.judge_protocol) return "mismatch";
    } else if (keys.some(key => scored[key] !== undefined) || scored.judge !== "J1") return "mismatch";
  }
  const same = (slotted || scored.rubric_sha256 === record.rubric_sha256) && (record.textV2 ?? record.judge) !== null && scored.judgment_sha256 === tableSha256(record.textV2 ?? record.judge) &&
    scored.response_sha256 === record.response_sha256 && scored.case_presentation_sha256 === record.case_presentation_sha256;
  return same ? "current" : "mismatch";
}

export function loadResponseRows(dir: string, caseId: string, tables: TableVersion[]): ResponseRow[] {
  const items = new Set(readItems(dir).filter((i) => baseId(i) === caseId).map((i) => i.id));
  const hashes = new Map(tables.map((t) => [t.version, t.status === "pass" ? t.sha256 : null]));
  const source = readJson<CaseSource>(inside(dir, "cases", `${caseId}.json`));
  const provenancePath = inside(dir, "provenance.json");
  const provenance = existsSync(provenancePath) ? readJson<Record<string, unknown>>(provenancePath) : {};
  const shared = sharedRubric(tables, provenance, caseId);
  const edits = caseEdits(source);
  const rows: ResponseRow[] = [];
  for (const model of listModels(dir)) {
    const judged = readJsonl<JudgeRecord>(inside(dir, "results", "judge", `${model}.jsonl`)).map(record => {
      const native = record.judge as unknown as TextV2Judgment | null;
      return native?.profile === "text-rubric-v2" ? { ...record, judge: null, textV2: native } : record;
    });
    const scored = readJsonl<ScoredRecord | TextV2Score>(inside(dir, "results", `${model}_scored.jsonl`));
    const groups = new Map<string, ResponseRecord[]>();
    for (const r of readJsonl<ResponseRecord>(inside(dir, "results", "responses", `${model}.jsonl`))) {
      if (!items.has(r.id)) continue;
      const trial = r.trial === undefined ? 1 : r.trial;
      const key = JSON.stringify([r.id, typeof trial, trial]);
      groups.set(key, [...(groups.get(key) ?? []), r]);
    }
    for (const records of groups.values()) {
      // A retried call leaves its error record first; the successful record is the response.
      const ready = records.filter((x) => !responseError(x));
      const r = ready.at(-1) ?? records[records.length - 1];
      const trial = r.trial === undefined ? 1 : r.trial;
      const error = ready.length > 1 ? "Multiple successful responses have this item/model/trial identity. Resolve the duplicate records before grading." : responseError(r);
      const matches = judged.filter((j) => j.id === r.id && j.trial === trial);
      const selected = error ? null : matches.at(-1) ?? null;
      const duplicateJudgments = matches.filter((j) => j.status === "pass").length > 1;
      const record = selected && duplicateJudgments
        ? { ...selected, errors: [...selected.errors, "Multiple successful judgments have this item/model/trial identity. Resolve the duplicate records before scoring."] }
        : selected;
      const judge = error ? "no response" : duplicateJudgments ? "failed" : judgeState(r, record, hashes, caseId, source.presentation, provenance, shared);
      const found = judge === "pass" && record ? scored.filter((s) => s.id === r.id && s.trial === trial).at(-1) ?? null : null;
      const check = found && record ? scoreCheck(found, record, hashes, shared) : null;
      const finished = judge === "pass" && record ? currentFinishedReview(dir, model, record) : null;
      const outdated = outdatedResponse(edits, model, r.id, trial, r.response ?? null, r.input_sha256 ?? null);
      rows.push({
        itemId: r.id, model, trial, response: r.response ?? null, responseError: error, judge, record,
        ...(r.route ? { route: r.route } : {}),
        ...(outdated ? { outdated } : {}),
        ...(finished ? { finishedReview: { reviewer: finished.reviewer, reviewedAt: finished.reviewedAt, readingSha256: finished.readingSha256, rubricReviewed: finished.rubricReviewed }, reviewedReading: finished.reading } : {}),
        judgeCommand: judgeCommand(dir, judgeRubric(tables, record)),
        scored: check === "mismatch" || found && "scorer" in found && found.scorer === "S2" ? null : found as ScoredRecord | null,
        ...(check === "current" && found && "scorer" in found && found.scorer === "S2" ? { textV2Score: found as TextV2Score } : {}), scoreCheck: check,
      });
    }
  }
  return rows.sort((a, b) => a.model.localeCompare(b.model) || a.itemId.localeCompare(b.itemId) || a.trial - b.trial);
}

// The score stage writes these bullets only with --allow-partial; without a report there is nothing to parse.
export function coverageGaps(report: string): string[] {
  const lines = report.split("\n");
  const start = lines.indexOf("Coverage gaps (partial report):");
  if (start < 0) return [];
  const gaps: string[] = [];
  for (const line of lines.slice(start + 1)) {
    if (!line.startsWith("- ")) break;
    gaps.push(line.slice(2));
  }
  return gaps;
}

function casesetArg(dir: string): string {
  const relative = path.relative(KIT_ROOT, dir);
  const shown = relative.startsWith("..") || path.isAbsolute(relative) ? dir : relative;
  return /\s/.test(shown) ? `'${shown}'` : shown;
}

// The judgment's own rubric when it has one; else a passing reviewed table, else the first passing run.
export function judgeRubric(tables: TableVersion[], record: JudgeRecord | null): string {
  if (record) return record.rubric;
  const passing = tables.filter((t) => t.status === "pass" && (t.record || t.textV2));
  return (passing.find((t) => t.kind === "reviewed") ?? passing.find((t) => t.kind === "run"))?.version ?? "<version>";
}

const judgeCommand = (dir: string, rubric: string): string => `.venv/bin/python tools/noharm.py judge ${casesetArg(dir)} --rubric ${rubric}`;

export function stageCommands(dir: string, caseId = "<ID>", judge = judgeCommand(dir, "<version>")): StageCommands {
  const cs = casesetArg(dir);
  const py = ".venv/bin/python";
  return {
    import: `${py} tools/noharm.py import ${cs} --case ${caseId}`,
    generate: `${py} tools/noharm.py generate ${cs} --case ${caseId}`,
    inference: `${py} tools/run_inference.py ${cs} --model <litellm-model-id>`,
    judge,
    score: `${py} tools/noharm.py score ${cs}`,
  };
}

export function loadCasePage(root: string, caseset: string, caseId: string): CasePage {
  const dir = casesetDir(root, caseset);
  assertCase(dir, caseId);
  const source = readJson<CaseSource>(inside(dir, "cases", `${caseId}.json`));
  const loaded = listVersionLabels(dir, caseId).map((label) => loadTableVersion(dir, caseId, label));
  const outdated = outdatedRubrics(dir, caseId, caseEdits(source), loaded);
  const tables = loaded.map((table) => outdated.has(table.version) ? { ...table, outdated: outdated.get(table.version) } : table);
  const report = inside(dir, "results", "report.md");
  const provenance = inside(dir, "provenance.json");
  const responses = loadResponseRows(dir, caseId, tables);
  const needsJudge = responses.find((r) => r.judge === "not run" || r.judge === "stale" || r.judge === "unverified" || r.judge === "failed");
  return {
    caseset,
    caseId,
    source,
    tables,
    responses,
    provenance: existsSync(provenance) ? readJson<Record<string, unknown>>(provenance) : {},
    report: existsSync(report) ? { gaps: coverageGaps(readFileSync(report, "utf8")) } : null,
    clinicianReviewed: tables.some((t) => t.kind === "reviewed" && t.status === "pass"),
    commands: stageCommands(dir, caseId, needsJudge?.judgeCommand ?? judgeCommand(dir, judgeRubric(tables, null))),
  };
}

// `itemId` is the response's item id; for a baseline item it equals the case id.
export function loadLens(root: string, caseset: string, itemId: string, model: string, trial: string): Lens {
  const dir = casesetDir(root, caseset);
  const item = readItems(dir).find((i) => i.id === itemId);
  if (!item) throw new NotFoundError(`no item ${itemId}`);
  assertModel(dir, model);
  if (!/^[1-9]\d*$/.test(trial)) throw new NotFoundError(`no trial ${trial}`);
  const page = loadCasePage(root, caseset, baseId(item));
  const row = page.responses.find((r) => r.itemId === itemId && r.model === model && r.trial === Number(trial));
  if (!row) throw new NotFoundError(`no response for ${itemId} ${model} trial ${trial}`);
  return { page, row, table: page.tables.find((t) => t.version === row.record?.rubric) ?? null };
}

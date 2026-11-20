import { expectedTrial, projectTrials, trialNumbers } from "@/lib/caseset/trials";
import { existsSync } from "node:fs";

import { tableSha256 } from "@/lib/caseset/hash";
import { provisionalReasons } from "@/lib/caseset/lens";
import { buildLeaderboard } from "@/lib/caseset/leaderboard";
import { caseIds, casesetDir, inside, listCasesetNames, listModels } from "@/lib/caseset/paths";
import { disagreementCount, judgeRubric, loadCasePage, readJson, readJsonl, sharedRubric } from "@/lib/caseset/read";
import { autogradingItem, latestReview, readReviews, reviewState } from "@/lib/caseset/reviews";
import type { ReviewRecord, ReviewState } from "@/lib/caseset/reviews";
import type { CasePage, Item, ResponseRow, TableVersion } from "@/lib/caseset/types";

import type { DotState, StepKey } from "@/lib/caseset/steps";

export { isStepKey, STEP_KEYS } from "@/lib/caseset/steps";
export type { DotState, StepKey } from "@/lib/caseset/steps";
export type RubricState = ReviewState | "none";

export interface ClinicianReview { reviewer: string; reviewedAt: string; readingSha256: string; rubricReviewed: boolean }
export interface ResponseStatus { caseId: string; row: ResponseRow; autograding: ReviewState | null; clinicianReview: ClinicianReview | null; scoreBehindReview: boolean; scoreReviewed: boolean; limits: string[] }
export interface MissingAnswer { caseId: string; itemId: string; model: string; trial: number }
export interface CaseRubric { state: RubricState; versions: string[]; hasPassing: boolean; failed: boolean; mixed: boolean; disagreements: number; outOfDate: string[]; basedOnOlder: string[]; unusedReviewed: string[] }
export interface CaseStatus { caseId: string; page: CasePage; items: string[]; prompts: Record<string, string>; rubric: CaseRubric; versionStates: Record<string, ReviewState>; responses: ResponseStatus[]; missing: MissingAnswer[] }
export interface StepSummary { key: StepKey; done: number; total: number; reviewed: number | null; reviewTotal: number | null; failed: number; dot: DotState }
export type AttentionKey = "failedRubrics" | "failedAutograding" | "missingAnswers" | "unexpectedAnswers" | "staleAutograding" | "unverifiedAutograding" | "disagreements" | "reviewOutOfDate" | "provisionalScores" | "mixedRubrics" | "unusedReview";
export type AttentionTarget = { case: string; version?: string; item?: string; model?: string; trial?: number };
export interface AttentionRow { key: AttentionKey; label: string; detail: string; count: number; step: StepKey; cases: string[]; target: AttentionTarget | null }
export interface F1Summary { value: number | null; n: number; draft: boolean; provisional: boolean }

export interface Benchmark {
  name: string;
  trials?: number;
  updatedAt: string | null;
  models: string[];
  cases: CaseStatus[];
  steps: Record<StepKey, StepSummary>;
  attention: AttentionRow[];
  needAttention: number;
  awaiting: { rubrics: number; autograding: number };
  meanF1: F1Summary;
  byModel: Array<F1Summary & { model: string }>;
}

export function rubricReviewProgress(cases: CaseStatus[]): { savedReviewed: number; savedTotal: number; usedReviewed: number; usedTotal: number } {
  const saved = cases.filter((c) => c.rubric.hasPassing);
  const used = cases.filter((c) => c.page.responses.some((r) => r.record !== null));
  const reviewedTable = (c: CaseStatus, version: string): boolean => c.page.tables.some((t) => t.version === version && t.status === "pass" && (t.record !== null || Boolean(t.textV2)) && c.versionStates[version] === "reviewed");
  return {
    savedReviewed: saved.filter((c) => c.page.tables.some((t) => reviewedTable(c, t.version))).length,
    savedTotal: saved.length,
    usedReviewed: used.filter((c) => c.page.responses.every((r) => !r.record || (r.judge === "pass" && reviewedTable(c, r.record.rubric)))).length,
    usedTotal: used.length,
  };
}

// pipeline/e2e/project.py sanitize_model: every stage derives file names from it.
export const sanitizeModel = (model: string): string => model.replace(/[/:]/g, "-");

// A caseset in the legacy format has items but no cases folder; a new benchmark may have neither yet.
export function listBenchmarks(root: string): string[] {
  return listCasesetNames(root).filter((name) => existsSync(inside(root, name, "cases")) || !existsSync(inside(root, name, "items.jsonl")));
}

export function benchmarkUpdatedAt(root: string, name: string): string | null {
  const provenance = inside(root, name, "provenance.json");
  return existsSync(provenance) ? readJson<{ updated_at?: string }>(provenance).updated_at ?? null : null;
}

// One benchmark per kit. NOHARM_BENCHMARK picks one when a folder holds several; otherwise the only one, else the
// most recently updated (provenance updated_at, ties broken by name). Null when there is none.
export function chooseBenchmark(names: string[], updatedAt: Record<string, string | null>, requested: string | undefined): string | null {
  if (requested && names.includes(requested)) return requested;
  const ranked = [...names].sort((a, b) => (updatedAt[b] ?? "").localeCompare(updatedAt[a] ?? "") || a.localeCompare(b));
  return ranked[0] ?? null;
}

// Only the review store makes a copy Reviewed; a copy with no record predates the store and needs a re-save.
export function versionState(table: TableVersion, caseId: string, reviews: ReviewRecord[]): ReviewState {
  if (table.kind !== "reviewed") return "draft";
  const state = reviewState(reviews, "rubrics", caseId, table.version, table.sha256);
  return state === "draft" ? "out of date" : state;
}

function caseRubric(page: CasePage, reviews: ReviewRecord[]): CaseRubric {
  const own = page.tables;
  const hasPassing = own.some((t) => t.status === "pass" && (t.record !== null || Boolean(t.textV2)));
  const used = [...new Set(page.responses.flatMap((r) => (r.record ? [r.record.rubric] : [])))].sort();
  const next = judgeRubric(page.tables, null);
  const versions = used.length ? used : next === "<version>" ? [] : [next];
  const tables = versions.flatMap((v) => page.tables.filter((t) => t.version === v));
  const states = tables.map((t) => versionState(t, page.caseId, reviews));
  const allReviewed = versions.length > 0 && states.length === versions.length && states.every((s) => s === "reviewed");
  const reviewedCopies = page.tables.filter((t) => t.kind === "reviewed");
  const hasAutograding = page.responses.some((r) => r.record !== null);
  return {
    state: !versions.length ? "none" : allReviewed ? "reviewed" : states.includes("out of date") ? "out of date" : "draft",
    versions,
    hasPassing,
    failed: own.length > 0 && !hasPassing,
    mixed: used.length > 1,
    disagreements: tables.reduce((n, t) => n + (disagreementCount(t.ratings) ?? 0), 0),
    // A passing reviewed copy that no autograding record references, while autograding exists for the case.
    unusedReviewed: hasAutograding
      ? reviewedCopies.filter((t) => t.status === "pass" && (t.record !== null || Boolean(t.textV2)) && versionState(t, page.caseId, reviews) === "reviewed" && !used.includes(t.version)).map((t) => t.version)
      : [],
    outOfDate: reviewedCopies.filter((t) => versionState(t, page.caseId, reviews) === "out of date").map((t) => t.version),
    basedOnOlder: reviewedCopies.filter((t) => {
      const source = page.tables.find((x) => x.version === t.basedOn?.version);
      return source !== undefined && source.sha256 !== null && source.sha256 !== t.basedOn?.sha256;
    }).map((t) => t.version),
  };
}

function responseStatus(row: ResponseRow, page: CasePage, reviews: ReviewRecord[]): ResponseStatus {
  const judge = row.judge === "pass" ? (row.record?.textV2 ?? row.record?.judge) ?? null : null;
  const item = autogradingItem(row.itemId, row.model, row.trial);
  const pipelineV2 = row.record?.judge_protocol === "J2.3";
  // A clinician review records the judge reading it started from; it counts only with a current finished line.
  const latest = judge && pipelineV2 ? latestReview(reviews, "autograding", page.caseId, item) : null;
  const autograding: ReviewState | null = !judge ? null
    : !pipelineV2 ? reviewState(reviews, "autograding", page.caseId, item, tableSha256(judge))
    : !latest ? "draft"
    : latest.basedOnSha256 === tableSha256(judge) && row.finishedReview ? "reviewed" : "out of date";
  const clinicianReview = autograding === "reviewed" && pipelineV2 ? row.finishedReview ?? null : null;
  const reviewedReading = clinicianReview !== null && row.textV2Score?.reviewedReadingSha256 === clinicianReview.readingSha256;
  // Current-grading scores are made against the case's shared rubric, whose label can differ from the judgment's.
  const label = pipelineV2 ? sharedRubric(page.tables, page.provenance, page.caseId).label : row.record?.rubric;
  const table = judge ? page.tables.find((t) => t.version === label) : undefined;
  const rubricReviewed = table !== undefined && versionState(table, page.caseId, reviews) === "reviewed";
  return {
    caseId: page.caseId,
    row,
    autograding,
    clinicianReview,
    scoreBehindReview: clinicianReview !== null && row.textV2Score !== undefined && !reviewedReading,
    // An unverified score has no recorded inputs, so no review can vouch for it.
    scoreReviewed: (row.scored !== null || Boolean(row.textV2Score)) && row.scoreCheck === "current" && autograding === "reviewed"
      && (pipelineV2 ? reviewedReading && rubricReviewed : rubricReviewed),
    limits: row.textV2Score ? [...(row.textV2Score.provisional ? ["unresolved error severity"] : []), ...(row.scoreCheck === "unverified" ? ["score inputs not recorded"] : [])] : row.scored ? [...provisionalReasons(row.scored), ...(row.scoreCheck === "unverified" ? ["score inputs not recorded"] : [])] : [],
  };
}

function missingAnswers(caseId: string, items: string[], rows: ResponseRow[], models: string[], trials: number): MissingAnswer[] {
  const seen = new Set(rows.filter((r) => expectedTrial(r.trial, trials)).map((r) => `${r.itemId}\t${r.model}\t${r.trial}`));
  return models.flatMap((model) => items.flatMap((itemId) => trialNumbers(trials)
    .filter((trial) => !seen.has(`${itemId}\t${model}\t${trial}`))
    .map((trial) => ({ caseId, itemId, model, trial }))));
}

function expectedModels(dir: string): string[] {
  const file = inside(dir, "provenance.json");
  const listed = existsSync(file) ? readJson<{ models?: string[] }>(file).models ?? [] : [];
  return [...new Set([...listed.map(sanitizeModel), ...listModels(dir)])].sort();
}

// failed beats nothing-done; a step is reviewed only when all of it is done and all of it reviewed.
function reviewable(key: StepKey, done: number, total: number, reviewed: number, failed: number): StepSummary {
  const dot: DotState = failed ? "bad" : done === 0 ? "none" : done === total && reviewed === done ? "reviewed" : "draft";
  return { key, done, total, reviewed, reviewTotal: done, failed, dot };
}

function f1Summary(rows: ResponseStatus[]): F1Summary {
  const scored = rows.filter((r) => r.row.scored !== null);
  return {
    value: scored.length ? scored.reduce((n, r) => n + (r.row.scored?.f1 ?? 0), 0) / scored.length : null,
    n: scored.length,
    draft: scored.some((r) => !r.scoreReviewed),
    provisional: scored.some((r) => r.limits.length > 0),
  };
}

const casesOf = (list: Array<{ caseId: string }>): string[] => [...new Set(list.map((x) => x.caseId))].sort();

export function loadBenchmark(root: string, name: string): Benchmark {
  const dir = casesetDir(root, name);
  const reviews = readReviews(dir);
  const allItems = readJsonl<Item>(inside(dir, "items.jsonl"));
  const pages = caseIds(dir).map((id) => loadCasePage(root, name, id));
  const models = expectedModels(dir);
  const provenance = inside(dir, "provenance.json");
  const trials = projectTrials(existsSync(provenance) ? readJson<{ trials?: unknown }>(provenance).trials : undefined);
  const cases: CaseStatus[] = pages.map((page) => {
    const own = allItems.filter((i) => (i.metadata?.base_id ?? i.id) === page.caseId);
    const items = own.map((i) => i.id);
    return {
      caseId: page.caseId,
      page,
      items,
      prompts: Object.fromEntries(own.map((i) => [i.id, i.prompt ?? ""])),
      rubric: caseRubric(page, reviews),
      versionStates: Object.fromEntries(page.tables.map((t) => [t.version, versionState(t, page.caseId, reviews)])),
      responses: page.responses.map((row) => responseStatus(row, page, reviews)),
      missing: missingAnswers(page.caseId, items, page.responses, models, trials),
    };
  });

  const allRows = cases.flatMap((c) => c.responses);
  const rows = allRows.filter((r) => expectedTrial(r.row.trial, trials));
  const unexpected = allRows.filter((r) => !expectedTrial(r.row.trial, trials));
  const missing = cases.flatMap((c) => c.missing);
  const ok = rows.filter((r) => r.row.response !== null && !r.row.responseError);
  const judged = rows.filter((r) => r.autograding !== null);
  const scored = rows.filter((r) => r.row.scored !== null || Boolean(r.row.textV2Score));
  const errored = rows.filter((r) => r.row.responseError);
  const responsesFailed = errored.length + missing.length + unexpected.length;
  const leaderboard = buildLeaderboard({ models, cases, trials });
  const nativeScores = rows.filter(r => Boolean(r.row.textV2Score));
  const leaderboardSummary = nativeScores.length
    ? reviewable("leaderboard", new Set(scored.map(r => r.row.model)).size, models.length, models.filter(model => { const own = scored.filter(r => r.row.model === model); return own.length > 0 && own.every(r => r.scoreReviewed && !r.limits.length); }).length, 0)
    : reviewable("leaderboard", leaderboard.filter((m) => m.scored > 0).length, models.length, leaderboard.filter((m) => m.scored > 0 && m.reviewed === m.scored).length, 0);
  if (leaderboardSummary.dot === "none" && leaderboard.some((m) => m.scored > 0)) leaderboardSummary.dot = "draft";
  const steps: Record<StepKey, StepSummary> = {
    cases: { key: "cases", done: cases.length, total: cases.length, reviewed: null, reviewTotal: null, failed: 0, dot: cases.length ? "reviewed" : "none" },
    rubrics: reviewable("rubrics", cases.filter((c) => c.rubric.hasPassing).length, cases.length, cases.filter((c) => c.rubric.state === "reviewed").length, cases.filter((c) => c.rubric.failed).length),
    responses: { key: "responses", done: ok.length, total: rows.length + missing.length, reviewed: null, reviewTotal: null, failed: responsesFailed, dot: responsesFailed ? "bad" : ok.length ? "model" : "none" },
    autograding: reviewable("autograding", judged.length, ok.length, judged.filter((r) => r.autograding === "reviewed").length, rows.filter((r) => r.row.judge === "failed").length),
    scores: reviewable("scores", scored.length, judged.length, scored.filter((r) => r.scoreReviewed && !r.limits.length).length, 0),
    leaderboard: leaderboardSummary,
  };

  const outOfDateRubrics = cases.flatMap((c) => c.rubric.outOfDate.map((version) => ({ caseId: c.caseId, version })));
  const outOfDateAutograding = rows.filter((r) => r.autograding === "out of date");
  const failedTable = (c: CaseStatus): string | undefined => c.page.tables.find((t) => (t.status !== "pass" || (t.record === null && !t.textV2)))?.version;
  const disagreeing = cases.filter((c) => c.rubric.disagreements > 0);
  const disagreeingVersion = (c: CaseStatus): string | undefined => c.page.tables.find((t) => c.rubric.versions.includes(t.version) && (disagreementCount(t.ratings) ?? 0) > 0)?.version;
  const unused = cases.filter((c) => c.rubric.unusedReviewed.length > 0);
  const candidates: AttentionRow[] = [
    { key: "failedRubrics", label: "Failed rubrics", detail: "Drafts that did not pass validation", step: "rubrics", ...counted(cases.filter((c) => c.rubric.failed), (c) => ({ case: c.caseId, version: failedTable(c) })) },
    { key: "failedAutograding", label: "Failed autograding", detail: "The autograder returned no usable result", step: "autograding", ...counted(rows.filter((r) => r.row.judge === "failed"), rowTarget) },
    { key: "unexpectedAnswers", label: "Unexpected trials", detail: "Stored trials outside the declared project range are excluded from coverage and ranking", step: "responses", ...counted(unexpected, rowTarget) },
    { key: "missingAnswers", label: "Missing model responses", detail: "A model returned nothing or an error", step: "responses", ...counted<ResponseStatus | MissingAnswer>([...errored, ...missing], (x) => ("row" in x ? rowTarget(x) : answerTarget(x))) },
    { key: "staleAutograding", label: "Out-of-date autograding", detail: "The rubric, model response, or input changed after autograding", step: "autograding", ...counted(rows.filter((r) => r.row.judge === "stale"), rowTarget) },
    { key: "unverifiedAutograding", label: "Unverified autograding inputs", detail: "Autograding did not record all of its inputs", step: "autograding", ...counted(rows.filter((r) => r.row.judge === "unverified"), rowTarget) },
    { key: "unusedReview", label: "Reviewed rubric not used", detail: "Autograding still uses an earlier draft", step: "autograding", ...counted(unused, (c) => ({ case: c.caseId })) },
    { key: "disagreements", label: "Committee disagreements", detail: "Raters split on a harm level", step: "rubrics", count: cases.reduce((n, c) => n + c.rubric.disagreements, 0), cases: casesOf(disagreeing), target: disagreeing[0] ? { case: disagreeing[0].caseId, version: disagreeingVersion(disagreeing[0]) } : null },
    { key: "reviewOutOfDate", label: "Review out of date", detail: "Content changed after a clinician reviewed it", step: outOfDateRubrics.length ? "rubrics" : "autograding", ...counted([...outOfDateRubrics, ...outOfDateAutograding], (x) => ("version" in x ? { case: x.caseId, version: x.version } : rowTarget(x))) },
    { key: "provisionalScores", label: "Provisional scores", detail: "Scores that rest on a provisional reading", step: "scores", ...counted(scored.filter((r) => r.limits.length > 0), rowTarget) },
    { key: "mixedRubrics", label: "Mixed rubric versions", detail: "Autograding used more than one rubric version", step: "autograding", ...counted(cases.filter((c) => c.rubric.mixed), (c) => ({ case: c.caseId })) },
  ];
  const attention = candidates.filter((a) => a.count > 0);
  return {
    name,
    trials,
    updatedAt: benchmarkUpdatedAt(root, name),
    models,
    cases,
    steps,
    attention,
    needAttention: attention.reduce((n, a) => n + a.count, 0),
    awaiting: {
      rubrics: cases.filter((c) => c.rubric.hasPassing && c.rubric.state !== "reviewed").length,
      autograding: judged.filter((r) => r.autograding !== "reviewed").length,
    },
    meanF1: f1Summary(rows),
    byModel: models.map((model) => ({ model, ...f1Summary(rows.filter((r) => r.row.model === model)) })),
  };
}

const rowTarget = (r: ResponseStatus): AttentionTarget => ({ case: r.caseId, item: r.row.itemId, model: r.row.model, trial: r.row.trial });
const answerTarget = (m: MissingAnswer): AttentionTarget => ({ case: m.caseId, item: m.itemId, model: m.model, trial: m.trial });

// `target` is the first affected item's identity, so a link lands on the item and not just its case.
function counted<T>(list: T[], target: (x: T) => AttentionTarget): { count: number; cases: string[]; target: AttentionTarget | null } {
  const of = list.map(target);
  return { count: list.length, cases: [...new Set(of.map((t) => t.case))].sort(), target: of[0] ?? null };
}

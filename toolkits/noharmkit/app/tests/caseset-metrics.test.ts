import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { tableSha256, textSha256 } from "../lib/caseset/hash";
import { baseReading, finishReview, saveDraft, type ReviewTarget } from "../lib/caseset/judgment-review-store";
import { preselected, reviewItems } from "../lib/caseset/judgment-review";
import { chooseBenchmark, listBenchmarks, loadBenchmark, rubricReviewProgress, sanitizeModel } from "../lib/caseset/metrics";
import type { Benchmark } from "../lib/caseset/metrics";
import { loadTableVersion } from "../lib/caseset/read";
import { appendReview, autogradingItem } from "../lib/caseset/reviews";
import type { ReviewRecord } from "../lib/caseset/reviews";
import { eachCase } from "./cases";
import { addReviewed, buildFixture, CASESET, JUDGE, MODEL_A, MODEL_B, RESPONSE, REVIEWED_FILE, TABLE, writeCasesetFile } from "./caseset-fixture";
import type { Fixture } from "./caseset-fixture";

const MODEL_C = "openrouter-test-model-c";
const review = (over: Partial<ReviewRecord> = {}): ReviewRecord => ({
  step: "rubrics", caseId: "Test002", item: "reviewed-dwu", contentSha256: tableSha256(TABLE), reviewer: "dwu", reviewedAt: "2026-09-29T17:00:00.000Z", ...over,
});
const load = (f: Fixture, name = CASESET): Benchmark => loadBenchmark(f.root, name);
const steps = (b: Benchmark): unknown[] => Object.values(b.steps).map((s) => [s.key, s.done, s.total, s.reviewed, s.failed, s.dot]);
const jsonl = (rows: unknown[]): string => rows.map((r) => `${JSON.stringify(r)}\n`).join("");

// Judges model A against the reviewed copy, scores it, and records both reviews.
function reviewEverything(f: Fixture, provisional = false, hashes = true): void {
  addReviewed(f);
  const inputs = { response_sha256: textSha256(RESPONSE), case_presentation_sha256: textSha256("A 67-year-old man with palpitations.") };
  writeCasesetFile(f, `results/judge/${MODEL_A}.jsonl`, jsonl([{ id: "Test002", trial: 1, caseId: "Test002", rubric: "reviewed-dwu", rubric_sha256: tableSha256(TABLE), ...inputs, status: "pass", judge: JUDGE, errors: [], raw: "{}", provenance: {} }]));
  writeCasesetFile(f, `results/judge/${MODEL_B}.jsonl`, "");
  writeCasesetFile(f, `results/${MODEL_A}_scored.jsonl`, jsonl([{
    id: "Test002", trial: 1, rubric: "reviewed-dwu", caseId: "Test002",
    decisions: { D1: { state: "scored", outcome: "met", credit: 1, events: [] }, D2: { state: "scored", outcome: "met", credit: 1, events: [] } },
    worstHarm: "none", recall: 1, precision: 1, f1: 1, provisional, offRubricProvisional: provisional, judgeModel: "j",
    ...(hashes ? { rubric_sha256: tableSha256(TABLE), judgment_sha256: tableSha256(JUDGE), ...inputs } : {}),
  }]));
  appendReview(f.dir, review());
  appendReview(f.dir, review({ step: "autograding", item: autogradingItem("Test002", MODEL_A, 1), contentSha256: tableSha256(JUDGE) }));
}

test("benchmark discovery and model file names", () => {
  // Benchmarks are casesets with a cases folder or nothing yet; the legacy format is left out.
  const f = buildFixture();
  mkdirSync(path.join(f.root, "fresh"));
  assert.deepEqual(listBenchmarks(f.root), [CASESET, "fresh"]);
  assert.equal(sanitizeModel("openrouter/openai/gpt-6:free"), "openrouter-openai-gpt-6-free");
});

test("fixture steps, attention rows, totals and targets", () => {
  const f = buildFixture();
  const b = load(f);
  assert.deepEqual(b.models, [MODEL_A, MODEL_B]);
  assert.deepEqual(steps(b), [
    ["cases", 1, 1, null, 0, "reviewed"],
    ["rubrics", 1, 1, 0, 0, "draft"],
    ["responses", 2, 2, null, 1, "bad"],
    ["autograding", 1, 2, 0, 0, "draft"],
    ["scores", 1, 1, 0, 0, "draft"],
    ["leaderboard", 1, 2, 0, 0, "draft"],
  ]);
  assert.deepEqual(b.attention.map((a) => [a.key, a.count, a.step, a.cases]), [
    ["unexpectedAnswers", 1, "responses", ["Test002"]],
    ["staleAutograding", 1, "autograding", ["Test002"]],
    ["disagreements", 1, "rubrics", ["Test002"]],
  ]);
  assert.equal(b.needAttention, 3);
  assert.deepEqual(b.awaiting, { rubrics: 1, autograding: 1 });
  assert.deepEqual(b.meanF1, { value: 1, n: 1, draft: true, provisional: false });
  assert.deepEqual(b.byModel.map((m) => [m.model, m.value, m.n]), [[MODEL_A, 1, 1], [MODEL_B, null, 0]]);
  assert.deepEqual(b.cases[0].rubric.versions, ["run1"]);
  assert.equal(b.cases[0].rubric.state, "draft");
  assert.deepEqual(b.cases[0].versionStates, { run1: "draft", run2: "draft", run3: "draft" });
  // Attention rows carry the identity of the first affected item.
  const row = (key: string) => b.attention.find((a) => a.key === key)?.target;
  assert.deepEqual(row("unexpectedAnswers"), { case: "Test002", item: "Test002", model: MODEL_A, trial: 2 });
  assert.deepEqual(row("staleAutograding"), { case: "Test002", item: "Test002", model: MODEL_B, trial: 1 });
  assert.deepEqual(row("disagreements"), { case: "Test002", version: "run1" });
  // A failed rubric targets its failed version.
  writeCasesetFile(f, "answer-tables/Test002.run1.status.json", { status: "failed", errors: ["x"] });
  writeCasesetFile(f, "answer-tables/Test002.run3.status.json", { status: "failed", errors: ["x"] });
  assert.deepEqual(load(f).attention.find((a) => a.key === "failedRubrics")?.target, { case: "Test002", version: "run1" });
});

test("missing answers with a listed model that has no file", () => {
  // A missing answer with no error record is still the target.
  const f = buildFixture();
  writeCasesetFile(f, "provenance.json", { updated_at: "2026-09-28T21:53:27+00:00", models: ["openrouter/test/model-a", "openrouter/test/model-b", "openrouter/test/model-c"] });
  // Historical trials outside the default range do not change expected coverage.
  assert.equal(load(f).attention.find((a) => a.key === "missingAnswers")?.count, 1);
  writeCasesetFile(f, `results/responses/${MODEL_A}.jsonl`, jsonl([{ id: "Test002", trial: 1, response: RESPONSE }]));
  assert.deepEqual(load(f).attention.find((a) => a.key === "missingAnswers")?.target, { case: "Test002", item: "Test002", model: MODEL_C, trial: 1 });

  // Missing answers keep item, model, and trial, and a listed model with no file counts.
  const v = buildFixture();
  writeCasesetFile(v, "items.jsonl", jsonl([
    { id: "Test002", prompt: "base prompt", metadata: { base_id: "Test002" } },
    { id: "Test002-1", prompt: "variant prompt", metadata: { base_id: "Test002" } },
  ]));
  writeCasesetFile(v, "provenance.json", { updated_at: "2026-09-28T21:53:27+00:00", models: ["openrouter/test/model-a", "openrouter/test/model-b", "openrouter/test/model-c"] });
  const b = load(v);
  const c = b.cases[0];
  assert.deepEqual(c.items, ["Test002", "Test002-1"]);
  assert.equal(c.prompts["Test002-1"], "variant prompt");
  assert.deepEqual(c.missing.map((m) => [m.itemId, m.model, m.trial]), [
    ["Test002-1", MODEL_A, 1], ["Test002-1", MODEL_B, 1], ["Test002", MODEL_C, 1], ["Test002-1", MODEL_C, 1],
  ]);
  assert.deepEqual([b.steps.responses.done, b.steps.responses.total, b.steps.responses.failed], [2, 6, 5]);
});

const reviewedAndRecorded = (f: Fixture): void => { addReviewed(f); appendReview(f.dir, review()); };
const emptyJudges = (f: Fixture): void => {
  writeCasesetFile(f, `results/judge/${MODEL_A}.jsonl`, "");
  writeCasesetFile(f, `results/judge/${MODEL_B}.jsonl`, "");
};
const UNUSED: Array<{ name: string; setup: (f: Fixture) => void; flagged: boolean; unusedReviewed?: string[] }> = [
  { name: "reviewed copy while autograding uses run1", setup: reviewedAndRecorded, flagged: true, unusedReviewed: ["reviewed-dwu"] },
  {
    name: "reviewed copy that model B was autograded with",
    setup: (f) => {
      reviewedAndRecorded(f);
      writeCasesetFile(f, `results/judge/${MODEL_B}.jsonl`, jsonl([{ id: "Test002", trial: 1, caseId: "Test002", rubric: "reviewed-dwu", rubric_sha256: tableSha256(TABLE), status: "pass", judge: JUDGE, errors: [], raw: "{}", provenance: {} }]));
    },
    flagged: false,
    unusedReviewed: [],
  },
  { name: "reviewed copy with no autograding at all", setup: (f) => { reviewedAndRecorded(f); emptyJudges(f); }, flagged: false },
  { name: "unreviewed copy", setup: (f) => addReviewed(f), flagged: false },
];

test("unusedReview flag", () => eachCase(UNUSED, (c) => c.name, (c) => {
  const f = buildFixture();
  c.setup(f);
  const b = load(f);
  if (c.unusedReviewed) assert.deepEqual(b.cases[0].rubric.unusedReviewed, c.unusedReviewed);
  const row = b.attention.find((a) => a.key === "unusedReview");
  if (c.flagged) assert.deepEqual([row?.label, row?.detail, row?.step, row?.count, row?.cases, row?.target], ["Reviewed rubric not used", "Autograding still uses an earlier draft", "autograding", 1, ["Test002"], { case: "Test002" }]);
  else assert.equal(row, undefined);
}));

type Progress = ReturnType<typeof rubricReviewProgress>;
const editReviewedCopy = (f: Fixture): void => writeCasesetFile(f, "answer-tables/Test002.reviewed-dwu.json", { ...REVIEWED_FILE, record: { ...TABLE, usualCare: { harm: "severe" } } });
const PROGRESS: Array<{ name: string; cases: () => Benchmark["cases"]; expected: Progress }> = [
  // Saved rubric review is independent of the rubrics used in existing results.
  { name: "reviewed only", cases: () => { const f = buildFixture(); reviewedAndRecorded(f); return load(f).cases; }, expected: { savedReviewed: 1, savedTotal: 1, usedReviewed: 0, usedTotal: 1 } },
  { name: "fully reviewed", cases: () => { const f = buildFixture(); reviewedAndRecorded(f); reviewEverything(f); return load(f).cases; }, expected: { savedReviewed: 1, savedTotal: 1, usedReviewed: 1, usedTotal: 1 } },
  { name: "reviewed copy edited after full review", cases: () => { const f = buildFixture(); reviewedAndRecorded(f); reviewEverything(f); editReviewedCopy(f); return load(f).cases; }, expected: { savedReviewed: 0, savedTotal: 1, usedReviewed: 0, usedTotal: 1 } },
  // Saved rubric review does not invent results before autograding.
  { name: "empty judge files", cases: () => { const f = buildFixture(); reviewedAndRecorded(f); emptyJudges(f); return load(f).cases; }, expected: { savedReviewed: 1, savedTotal: 1, usedReviewed: 0, usedTotal: 0 } },
  { name: "no cases", cases: () => [], expected: { savedReviewed: 0, savedTotal: 0, usedReviewed: 0, usedTotal: 0 } },
  // Stale autograding cannot claim to use a current reviewed rubric.
  {
    name: "response changed after full review",
    cases: () => {
      const f = buildFixture();
      reviewEverything(f);
      writeCasesetFile(f, `results/responses/${MODEL_A}.jsonl`, jsonl([{ id: "Test002", trial: 1, response: `${RESPONSE} Changed.` }]));
      return load(f).cases;
    },
    expected: { savedReviewed: 1, savedTotal: 1, usedReviewed: 0, usedTotal: 1 },
  },
];

test("rubricReviewProgress", () => eachCase(PROGRESS, (c) => c.name, (c) => {
  assert.deepEqual(rubricReviewProgress(c.cases()), c.expected);
}));

test("a reviewed rubric is reviewed only while its content matches the review record", () => {
  // Loading never touches the reviewed file.
  const untouched = buildFixture();
  addReviewed(untouched);
  const reviewed = path.join(untouched.dir, "answer-tables", "Test002.reviewed-dwu.json");
  const before = readFileSync(reviewed, "utf8");
  load(untouched);
  assert.equal(readFileSync(reviewed, "utf8"), before);

  const f = buildFixture();
  writeCasesetFile(f, `results/judge/${MODEL_A}.jsonl`, "");
  writeCasesetFile(f, `results/judge/${MODEL_B}.jsonl`, "");
  addReviewed(f);
  assert.deepEqual(load(f).cases[0].rubric.versions, ["reviewed-dwu"]);
  assert.equal(load(f).cases[0].rubric.state, "out of date"); // a copy with no record predates the store
  appendReview(f.dir, review());
  let b = load(f);
  assert.equal(b.cases[0].rubric.state, "reviewed");
  assert.deepEqual([b.steps.rubrics.reviewed, b.steps.rubrics.dot, b.awaiting.rubrics], [1, "reviewed", 0]);
  writeCasesetFile(f, "answer-tables/Test002.reviewed-dwu.json", { ...REVIEWED_FILE, record: { ...TABLE, usualCare: { harm: "severe" } } });
  b = load(f);
  assert.equal(b.cases[0].rubric.state, "out of date");
  assert.equal(b.steps.rubrics.reviewed, 0);
  assert.deepEqual(b.attention.find((a) => a.key === "reviewOutOfDate")?.count, 1);
  writeCasesetFile(f, "answer-tables/Test002.run1.json", { ...TABLE, usualCare: { harm: "mild" } });
  assert.deepEqual(load(f).cases[0].rubric.basedOnOlder, ["reviewed-dwu"]);
});

test("reviewed autograding on an LLM-draft rubric does not make the score reviewed", () => {
  const f = buildFixture();
  appendReview(f.dir, review({ step: "autograding", item: autogradingItem("Test002", MODEL_A, 1), contentSha256: tableSha256(JUDGE) }));
  const b = load(f);
  const a = b.cases[0].responses.find((r) => r.row.model === MODEL_A && r.row.trial === 1);
  assert.equal(a?.autograding, "reviewed");
  assert.equal(a?.scoreReviewed, false);
  assert.deepEqual([b.steps.autograding.reviewed, b.awaiting.autograding], [1, 0]);
});

// A fully reviewed score is complete; a provisional one, or one without recorded inputs, never is.
const COMPLETENESS: Array<{
  name: string; provisional: boolean; hashes: boolean;
  done?: number; reviewed: number; dot: string; scoreReviewed?: boolean; limits?: string[]; scoreCheck?: string; provisionalScores?: number;
  meanF1: Benchmark["meanF1"];
}> = [
  { name: "fully reviewed", provisional: false, hashes: true, done: 1, reviewed: 1, dot: "reviewed", meanF1: { value: 1, n: 1, draft: false, provisional: false } },
  { name: "provisional", provisional: true, hashes: true, reviewed: 0, dot: "draft", scoreReviewed: true, limits: ["actionable off-rubric harm"], provisionalScores: 1, meanF1: { value: 1, n: 1, draft: false, provisional: true } },
  { name: "inputs not recorded", provisional: false, hashes: false, reviewed: 0, dot: "draft", scoreReviewed: false, limits: ["score inputs not recorded"], scoreCheck: "unverified", meanF1: { value: 1, n: 1, draft: true, provisional: true } },
];

test("score completeness", () => eachCase(COMPLETENESS, (c) => c.name, (c) => {
  const f = buildFixture();
  reviewEverything(f, c.provisional, c.hashes);
  const b = load(f);
  const a = b.cases[0].responses.find((r) => r.row.model === MODEL_A);
  if (c.done !== undefined) assert.equal(b.steps.scores.done, c.done);
  assert.deepEqual([b.steps.scores.reviewed, b.steps.scores.dot], [c.reviewed, c.dot]);
  if (c.scoreCheck !== undefined) assert.equal(a?.row.scoreCheck, c.scoreCheck);
  if (c.scoreReviewed !== undefined) assert.equal(a?.scoreReviewed, c.scoreReviewed);
  if (c.limits !== undefined) assert.deepEqual(a?.limits, c.limits);
  if (c.provisionalScores !== undefined) assert.equal(b.attention.find((x) => x.key === "provisionalScores")?.count, c.provisionalScores);
  assert.deepEqual(b.meanF1, c.meanF1);
}));

test("autograding against two rubric versions is mixed", () => {
  const f = buildFixture();
  addReviewed(f);
  writeCasesetFile(f, `results/judge/${MODEL_B}.jsonl`, jsonl([{ id: "Test002", trial: 1, caseId: "Test002", rubric: "reviewed-dwu", rubric_sha256: tableSha256(TABLE), status: "pass", judge: JUDGE, errors: [], raw: "{}", provenance: {} }]));
  const b = load(f);
  assert.deepEqual(b.cases[0].rubric.versions, ["reviewed-dwu", "run1"]);
  assert.equal(b.cases[0].rubric.mixed, true);
  assert.deepEqual(b.attention.find((x) => x.key === "mixedRubrics")?.step, "autograding");
});

test("a new benchmark shows every project case without study-specific exclusions", () => {
  const f = buildFixture();
  const cases = path.join(f.root, "fresh", "cases");
  mkdirSync(cases, { recursive: true });
  writeFileSync(path.join(cases, "Test010.json"), JSON.stringify({ presentation: "q", recommendations: "a" }));
  writeFileSync(path.join(cases, "Test008.json"), JSON.stringify({ presentation: "q", recommendations: "a" }));
  const b = load(f, "fresh");
  assert.deepEqual(b.cases.map((c) => c.caseId), ["Test008", "Test010"]);
  assert.deepEqual(steps(b), [
    ["cases", 2, 2, null, 0, "reviewed"],
    ["rubrics", 0, 2, 0, 0, "none"],
    ["responses", 0, 0, null, 0, "none"],
    ["autograding", 0, 0, 0, 0, "none"],
    ["scores", 0, 0, 0, 0, "none"],
    ["leaderboard", 0, 0, 0, 0, "none"],
  ]);
  assert.deepEqual(b.attention, []);
  assert.deepEqual(b.meanF1, { value: null, n: 0, draft: false, provisional: false });
});

test("one benchmark is chosen: the requested one, else the most recently updated", () => {
  const stamps = { a: "2026-09-01T00:00:00Z", b: "2026-09-02T00:00:00Z", c: null };
  assert.equal(chooseBenchmark(["a", "b", "c"], stamps, "a"), "a");
  assert.equal(chooseBenchmark(["a", "b", "c"], stamps, "nope"), "b");
  assert.equal(chooseBenchmark(["only"], {}, undefined), "only");
  assert.equal(chooseBenchmark(["c", "a"], stamps, undefined), "a");
  assert.equal(chooseBenchmark(["z", "m"], { z: null, m: null }, undefined), "m");
  assert.equal(chooseBenchmark(["y", "x"], { x: "2026-09-01T00:00:00Z", y: "2026-09-01T00:00:00Z" }, undefined), "x");
  assert.equal(chooseBenchmark([], {}, "a"), null);
});

// Clinician review of a pipeline-v2 judgment: finished lines and the score that uses them.
const V2_MODEL = "benchmark-hand-labeled";
const V2_NOW = new Date("2026-11-14T12:00:00.000Z");

const v2Row = (root: string): ReturnType<typeof load>["cases"][number]["responses"][number] | undefined =>
  loadBenchmark(root, "demo").cases[0].responses.find((r) => r.row.model === V2_MODEL);

function scoreUses(dir: string, reviewedReadingSha256: string): void {
  const file = path.join(dir, "results", `${V2_MODEL}_scored.jsonl`);
  const row = JSON.parse(readFileSync(file, "utf8").trim());
  writeFileSync(file, `${JSON.stringify({ ...row, reading: "clinician review", reviewer: "dw", reviewedAt: V2_NOW.toISOString(), reviewedReadingSha256, readingSha256: reviewedReadingSha256 })}\n`);
}

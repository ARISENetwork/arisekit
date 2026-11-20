import assert from "node:assert/strict";
import test from "node:test";

import { buildLeaderboard } from "../lib/caseset/leaderboard";
import type { LeaderboardRow } from "../lib/caseset/leaderboard";
import type { Benchmark, CaseStatus, MissingAnswer, ResponseStatus } from "../lib/caseset/metrics";
import type { ScoredRecord } from "../lib/caseset/types";
import { eachCase } from "./cases";

function score(over: Partial<ScoredRecord> = {}): ScoredRecord {
  return { id: "Case1", caseId: "Case1", trial: 1, rubric: "run1", rubric_sha256: "rubric-hash", judgment_sha256: "judgment-hash", decisions: {}, worstHarm: "none", recall: 0.8, precision: 0.8, f1: 0.8, provisional: false, offRubricProvisional: false, judgeModel: "judge-a", ...over };
}

function response(model: string, scored: ScoredRecord | null = score(), over: Partial<ResponseStatus> = {}): ResponseStatus {
  return {
    caseId: scored?.caseId ?? "Case1", autograding: "reviewed", clinicianReview: null, scoreBehindReview: false, scoreReviewed: true, limits: [],
    row: { itemId: scored?.id ?? "Case1", model, trial: scored?.trial ?? 1, response: "Synthetic answer", responseError: null, judge: "pass", record: null, judgeCommand: "judge", scored, scoreCheck: "current" },
    ...over,
  };
}

function caseStatus(caseId: string, responses: ResponseStatus[], missing: MissingAnswer[] = []): CaseStatus {
  return {
    caseId, responses, missing, items: [caseId], prompts: {}, versionStates: {},
    rubric: { state: "reviewed", versions: ["run1"], hasPassing: true, failed: false, mixed: false, disagreements: 0, outOfDate: [], basedOnOlder: [], unusedReviewed: [] },
    page: { caseset: "synthetic", caseId, source: { presentation: "Synthetic", recommendations: "Synthetic" }, tables: [], responses: responses.map((r) => r.row), provenance: {}, report: null, clinicianReviewed: true, commands: { import: "", generate: "", inference: "", judge: "", score: "" } },
  };
}

function benchmark(models: string[], responses: ResponseStatus[], missing: MissingAnswer[] = [], trials = 1): Pick<Benchmark, "models" | "cases" | "trials"> {
  const ids = [...new Set([...responses.map((r) => r.caseId), ...missing.map((r) => r.caseId)])];
  return { models, trials, cases: ids.map((id) => caseStatus(id, responses.filter((r) => r.caseId === id), missing.filter((r) => r.caseId === id))) };
}

test("means use stored response metrics and harm remains a response distribution", () => {
  const bench = benchmark(["b", "a"], [
    response("a", score({ id: "Case2", caseId: "Case2", trial: 1, f1: 0.6, recall: 0.4, precision: 0.8, worstHarm: "severe" })),
    response("b", score({ f1: 0.5 })),
    response("a", score({ f1: 1, recall: 1, precision: 1, worstHarm: "mild" })),
  ]);
  const rows = buildLeaderboard(bench);
  assert.deepEqual(rows.map((r) => r.model), ["a", "b"]);
  assert.equal(rows[0].f1, 0.8);
  assert.equal(rows[0].recall, 0.7);
  assert.equal(rows[0].precision, 0.9);
  assert.equal(rows[0].worstHarm, "severe");
  assert.deepEqual(rows[0].harmCounts, { none: 0, uncertain: 0, mild: 1, moderate: 0, severe: 1 });
  assert.deepEqual([rows[0].scored, rows[0].expected, rows[0].scoredCases, rows[0].totalCases, rows[0].reviewed], [2, 2, 2, 2, 2]);
  assert.deepEqual(rows[0].target, { case: "Case1", item: "Case1", model: "a", trial: 1 });
  assert.equal(rows[0].rank, 1);
});

test("failed, absent, and not-yet-scored responses stay in expected coverage without zero imputation", () => {
  const failed = response("a", null);
  failed.row.response = null;
  failed.row.responseError = "timeout";
  failed.row.judge = "no response";
  failed.row.trial = 2;
  const unscored = response("a", null);
  unscored.row.itemId = "Case2";
  unscored.caseId = "Case2";
  const rows = buildLeaderboard(benchmark(["a"], [response("a"), failed, unscored], [{ caseId: "Case2", itemId: "Case2", model: "a", trial: 2 }], 2));
  assert.deepEqual([rows[0].scored, rows[0].expected, rows[0].missing, rows[0].failed, rows[0].unscored], [1, 4, 2, 1, 3]);
  assert.deepEqual([rows[0].scoredCases, rows[0].totalCases], [1, 2]);
  assert.equal(rows[0].f1, 0.8);
  assert.equal(rows[0].rank, 1);
  assert.equal(rows[0].status, "partial");
});

test("models without scores remain visible after scored models with null metrics and harm", () => {
  const rows = buildLeaderboard(benchmark(["z", "a", "b"], [response("b", score({ f1: 0 }))]));
  assert.deepEqual(rows.map((r) => r.model), ["b", "a", "z"]);
  assert.equal(rows[0].f1, 0);
  assert.equal(rows[0].rank, 1);
  for (const r of rows.slice(1)) {
    assert.deepEqual([r.f1, r.recall, r.precision, r.worstHarm], [null, null, null, null]);
    assert.equal(r.status, "not scored");
  }
  assert.deepEqual(rows.map((r) => r.rank), [1, null, null]);
  assert.deepEqual(buildLeaderboard({ models: [], cases: [] }), []);
});

test("tied means share competition ranks and incomplete models occupy their score-order position", () => {
  const rows = buildLeaderboard(benchmark(["d", "c", "b", "a"], [response("d", score({ f1: 0.6 })), response("c", score({ f1: 1 })), response("b"), response("a"), response("d", score({ trial: 2, f1: 0.6 })), response("b", score({ trial: 2 })), response("a", score({ trial: 2 }))], [{ caseId: "Case1", itemId: "Case1", model: "c", trial: 2 }], 2));
  assert.deepEqual(rows.map((r) => [r.model, r.rank]), [["c", 1], ["a", 2], ["b", 2], ["d", 4]]);
});

test("draft, provisional, and unverified scores retain ranks while keeping their provenance flags", () => {
  const draft = response("draft", score(), { scoreReviewed: false, autograding: "draft" });
  const provisional = response("provisional", score({ provisional: true }));
  const offRubric = response("offrubric", score({ offRubricProvisional: true }));
  const unverified = response("unverified");
  unverified.row.scoreCheck = "unverified";
  unverified.limits = ["score inputs not recorded"];
  const rows = buildLeaderboard(benchmark(["draft", "provisional", "offrubric", "unverified"], [draft, provisional, offRubric, unverified]));
  const get = (model: string) => rows.find((r) => r.model === model)!;
  assert.equal(get("draft").rank, 1);
  assert.deepEqual([get("draft").draft, get("draft").draftCount, get("draft").reviewed], [true, 1, 0]);
  for (const name of ["provisional", "offrubric"]) {
    assert.equal(get(name).rank, 1);
    assert.deepEqual([get(name).provisional, get(name).provisionalCount, get(name).reviewed], [true, 1, 0]);
  }
  assert.equal(get("unverified").rank, 1);
  assert.equal(get("unverified").status, "unverified");
  assert.deepEqual([get("unverified").unverified, get("unverified").unverifiedCount, get("unverified").provisional, get("unverified").reviewed], [true, 1, false, 0]);
});

test("unscored models link to a response or the first missing expected item", () => {
  const absent = [
    { caseId: "Case2", itemId: "Case2", model: "missing", trial: 2 },
    { caseId: "Case1", itemId: "Case1-variant", model: "missing", trial: 1 },
  ];
  const rows = buildLeaderboard(benchmark(["missing", "unscored"], [response("unscored", null)], absent));
  assert.deepEqual(rows.find((r) => r.model === "missing")!.target, { case: "Case1", item: "Case1", model: "missing", trial: 1 });
  assert.deepEqual(rows.find((r) => r.model === "unscored")!.target, { case: "Case1", item: "Case1", model: "unscored", trial: 1 });
});

test("each declared trial contributes equally and an uncollected trial stays visible in ranked coverage", () => {
  const responses = [response("a", score({ trial: 1, f1: 0 })), response("a", score({ trial: 2, f1: 0.5 }))];
  let [row] = buildLeaderboard(benchmark(["a"], responses, [], 3));
  assert.deepEqual([row.f1, row.expected, row.scored, row.missing, row.rank], [0.25, 3, 2, 1, 1]);
  responses.push(response("a", score({ trial: 3, f1: 1 })));
  [row] = buildLeaderboard(benchmark(["a"], responses, [], 3));
  assert.deepEqual([row.f1, row.expected, row.scored, row.missing, row.rank], [0.5, 3, 3, 0, 1]);
});

const BAD_METRICS = [NaN, Infinity, -Infinity, -0.1, 1.1, null, undefined, "0.8"];

const EXCLUDED: Array<{ label: string; bench: () => Pick<Benchmark, "models" | "cases" | "trials">; pick: (row: LeaderboardRow) => unknown[]; expected: unknown[][] }> = [
  ...(["f1", "recall", "precision"] as const).flatMap((key) => BAD_METRICS.map((bad) => ({
    label: `${key}=${String(bad)} excludes the whole response from means and coverage`,
    bench: () => {
      const invalid = response("a", score({ [key]: bad } as Partial<ScoredRecord>));
      invalid.row.trial = 2;
      return benchmark(["a"], [response("a"), invalid], [], 2);
    },
    pick: (r: LeaderboardRow): unknown[] => [r.scored, r.expected, r.f1, r.rank],
    expected: [[1, 2, 0.8, 1]],
  }))),
  { label: "stale, failed, and mismatched scores are excluded even when finite",
    bench: () => {
      const stale = response("a");
      stale.row.judge = "stale";
      const failed = response("a");
      failed.row.judge = "failed";
      failed.row.trial = 2;
      const mismatch = response("a");
      mismatch.row.scoreCheck = "mismatch";
      mismatch.row.trial = 3;
      return benchmark(["a"], [stale, failed, mismatch], [], 3);
    },
    pick: (r) => [r.scored, r.expected, r.failed, r.f1],
    expected: [[0, 3, 1, null]] },
  { label: "scored artifacts on missing or failed responses do not contribute",
    bench: () => {
      const missing = response("a");
      missing.row.response = null;
      const failed = response("b");
      failed.row.responseError = "timeout";
      return benchmark(["a", "b"], [missing, failed]);
    },
    pick: (r) => [r.model, r.scored, r.expected, r.f1, r.rank],
    expected: [["a", 0, 1, null, null], ["b", 0, 1, null, null]] },
];

test("excluded responses do not contribute to means and coverage", () => eachCase(EXCLUDED, (c) => c.label, (c) => {
  assert.deepEqual(buildLeaderboard(c.bench()).map(c.pick), c.expected);
}));

const PROVENANCE: Array<{ label: string; responses: () => ResponseStatus[]; trials: number; pick: (row: LeaderboardRow) => unknown[]; expected: unknown[] }> = [
  { label: "uncertain and unknown harm are distinct, and mixed score provenance within a case is flagged",
    responses: () => [response("a", score({ worstHarm: "uncertain" })), response("a", score({ trial: 2, worstHarm: "unknown", rubric: "run2", judgeModel: "judge-b" }))], trials: 2,
    pick: (r) => [r.worstHarm, r.harmCounts.uncertain, r.harmCounts.none, r.unknownHarmCount, r.mixedRubrics, r.mixedJudges],
    expected: ["uncertain", 1, 0, 1, true, true] },
  { label: "different case-specific rubric identities are not mixed rubrics",
    responses: () => [response("a"), response("a", score({ id: "Case2", caseId: "Case2", rubric: "run2", rubric_sha256: "case2-hash" }))], trials: 1,
    pick: (r) => [r.mixedRubrics], expected: [false] },
];

test("harm categories and mixed-provenance flags", () => eachCase(PROVENANCE, (c) => c.label, (c) => {
  const [row] = buildLeaderboard(benchmark(["a"], c.responses(), [], c.trials));
  assert.deepEqual(c.pick(row), c.expected);
}));

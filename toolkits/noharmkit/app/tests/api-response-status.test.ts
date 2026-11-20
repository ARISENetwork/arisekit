import assert from "node:assert/strict";
import test from "node:test";

import type { ApiModelTeam } from "../lib/api-model-teams";
import { apiResponseRows, withApiResponseModels } from "../lib/api-response-status";
import { loadBenchmark } from "../lib/caseset/metrics";
import type { Benchmark, CaseStatus, ResponseStatus } from "../lib/caseset/metrics";
import { resolveStepParams } from "../lib/caseset/routes";
import { STEP_KEYS } from "../lib/caseset/steps";
import type { ResponseRoute } from "../lib/caseset/types";
import { buildFixture, CASESET, writeCasesetFile } from "./caseset-fixture";
import { eachCase } from "./cases";

const team: ApiModelTeam = { models: ["test/model-b", "test/model-a"], integrator: "", modelReasoning: { "test/model-b": "none" } };

function response(caseId: string, itemId: string, model: string, trial: number, text: string | null = "Synthetic response", error: string | null = null): ResponseStatus {
  return {
    caseId, autograding: "out of date", clinicianReview: null, scoreBehindReview: false, scoreReviewed: false, limits: ["unverified score"],
    row: { itemId, model, trial, response: text, responseError: error, judge: "failed", record: null, judgeCommand: "", scored: null, scoreCheck: null },
  };
}

function caseStatus(caseId: string, items: string[], responses: ResponseStatus[] = []): CaseStatus {
  return {
    caseId, items, responses, missing: [], prompts: {}, versionStates: {},
    rubric: { state: "none", versions: [], hasPassing: false, failed: false, mixed: false, disagreements: 0, outOfDate: [], basedOnOlder: [], unusedReviewed: [] },
    page: { caseset: "synthetic", caseId, source: { presentation: "Synthetic", recommendations: "Synthetic" }, tables: [], responses: responses.map(r => r.row), provenance: {}, report: null, clinicianReviewed: false, commands: { import: "", generate: "", inference: "", judge: "", score: "" } },
  };
}

function benchmark(cases: CaseStatus[] = [caseStatus("Case1", ["Case1"])], trials = 1): Benchmark {
  return {
    name: "synthetic", trials, updatedAt: null, models: ["historical-model"], cases,
    steps: Object.fromEntries(STEP_KEYS.map(key => [key, { key, done: 0, total: 0, reviewed: null, reviewTotal: null, failed: 0, dot: "none" }])) as Benchmark["steps"],
    attention: [], needAttention: 5, awaiting: { rubrics: 2, autograding: 3 }, meanF1: { value: null, n: 0, draft: true, provisional: true }, byModel: [],
  };
}

const PENDING_CASES: { label: string; bench: () => Benchmark; check: (rows: ReturnType<typeof apiResponseRows>) => void }[] = [
  {
    label: "two configured models in their saved order",
    bench: () => benchmark(),
    check: rows => {
      assert.deepEqual(rows, [
        { id: "test/model-b", model: "test-model-b", status: "Pending", completed: 0, failed: 0, pending: 1, total: 1, reasoning: "none" },
        { id: "test/model-a", model: "test-model-a", status: "Pending", completed: 0, failed: 0, pending: 1, total: 1 },
      ]);
      assert.equal(Object.hasOwn(rows[1], "reasoning"), false);
    },
  },
  {
    label: "unrelated items, trials, models and historical combined outputs",
    bench: () => benchmark([caseStatus("Case1", ["Case1"], [
      response("Case1", "unimported", "test-model-a", 1, null, "outside item"),
      response("Case1", "Case1", "test-model-a", 0), response("Case1", "Case1", "test-model-a", 2),
      response("Case1", "Case1", "test-model-a", 1.5),
      response("Case1", "Case1", "unselected-model", 1, null, "outside model"),
      response("Case1", "Case1", "integrated-response-abc", 1),
    ])]),
    check: rows => assert.ok(rows.every(row => row.status === "Pending" && row.completed === 0 && row.failed === 0 && row.pending === 1)),
  },
  { label: "empty imported dataset", bench: () => benchmark([]), check: rows => assert.ok(rows.every(row => row.status === "Pending" && row.total === 0)) },
  {
    label: "omitted trial policy defaults to one",
    bench: () => { const imported = benchmark(); delete imported.trials; return imported; },
    check: rows => assert.equal(rows[0].total, 1),
  },
];

test("pending coverage before any matching response", () => eachCase(PENDING_CASES, (c) => c.label, (c) => {
  c.check(apiResponseRows(c.bench(), team));
}));

test("response coverage alone decides complete, partial, blank and failed status", () => {
  const cases = [caseStatus("Case1", ["Case1"], [response("Case1", "Case1", "test-model-a", 1)])];
  assert.equal(apiResponseRows(benchmark(cases), team)[1].status, "Complete");
  const partial = benchmark(cases, 2);
  assert.deepEqual(apiResponseRows(partial, team)[1], { id: "test/model-a", model: "test-model-a", status: "Pending", completed: 1, failed: 0, pending: 1, total: 2 });
  cases[0].responses.push(response("Case1", "Case1", "test-model-a", 2, " \n "));
  assert.equal(apiResponseRows(partial, team)[1].pending, 1);
  cases[0].responses[1].row.response = null;
  assert.equal(apiResponseRows(partial, team)[1].pending, 1);
  cases[0].responses[1].row.responseError = "timeout";
  cases[0].responses[1].row.response = "Partial output with a transport error";
  assert.deepEqual(apiResponseRows(partial, team)[1], { id: "test/model-a", model: "test-model-a", status: "Failed", completed: 1, failed: 1, pending: 0, total: 2 });
});

test("coverage includes every imported item and declared trial across cases", () => {
  const cases = [caseStatus("Case1", ["Case1", "Case1-1"]), caseStatus("Case2", ["Case2"])];
  for (const c of cases) for (const item of c.items) for (const trial of [1, 2]) c.responses.push(response(c.caseId, item, "test-model-a", trial));
  cases[0].responses.push(response("Case1", "Case1", "test-model-b", 1), response("Case1", "Case1", "test-model-b", 2, null, "timeout"));
  const bench = benchmark(cases, 2);
  const rows = apiResponseRows(bench, team);
  assert.deepEqual(rows.map(({ completed, failed, pending, total, status }) => ({ completed, failed, pending, total, status })), [
    { completed: 1, failed: 1, pending: 4, total: 6, status: "Failed" },
    { completed: 6, failed: 0, pending: 0, total: 6, status: "Complete" },
  ]);
  const summary = withApiResponseModels(bench, team).steps.responses;
  assert.deepEqual([summary.done, summary.total, summary.failed, summary.dot], [7, 12, 1, "bad"]);
});

test("planned missing slots allow pending model and trial selection without duplicates", () => {
  const bench = benchmark([caseStatus("Case1", ["Case1", "Case1-1"])], 2);
  bench.steps.responses.failed = 8;
  bench.steps.responses.dot = "bad";
  bench.cases[0].missing.push({ caseId: "Case1", itemId: "Case1", model: "test-model-a", trial: 2 });
  const planned = withApiResponseModels(bench, team);
  assert.deepEqual(planned.models, ["historical-model", "test-model-b", "test-model-a"]);
  assert.equal(planned.cases[0].missing.length, 8);
  assert.equal(new Set(planned.cases[0].missing.map(slot => JSON.stringify(slot))).size, 8);
  const selected = resolveStepParams(planned, { case: "Case1", item: "Case1-1", model: "test-model-b", trial: "2" }, "responses");
  assert.deepEqual(selected, { caseId: "Case1", version: null, itemId: "Case1-1", model: "test-model-b", trial: 2 });
  for (const step of ["autograding", "scores"] as const) {
    assert.deepEqual(resolveStepParams(planned, { case: "Case1", item: "Case1-1", model: "test-model-b", trial: "2" }, step), selected);
  }
  const repeated = withApiResponseModels(planned, team);
  assert.deepEqual(repeated, planned);
  assert.deepEqual([planned.steps.responses.done, planned.steps.responses.total, planned.steps.responses.failed, planned.steps.responses.dot], [0, 8, 0, "none"]);
});

test("the Responses view preserves stored slots, other steps and both inputs", () => {
  const c = caseStatus("Case1", ["Case1"], [response("Case1", "Case1", "test-model-a", 1)]);
  c.missing.push({ caseId: "Case1", itemId: "Case1", model: "historical-model", trial: 1 });
  const bench = benchmark([c]);
  bench.models.push("test-model-a", "integrated-response-abc");
  const savedBench = structuredClone(bench);
  const savedTeam = structuredClone(team);
  const planned = withApiResponseModels(bench, team);
  assert.deepEqual(bench, savedBench);
  assert.deepEqual(team, savedTeam);
  assert.notEqual(planned, bench);
  assert.notEqual(planned.cases[0], c);
  assert.equal(planned.cases[0].page, c.page);
  assert.equal(planned.cases[0].responses, c.responses);
  assert.equal(planned.attention, bench.attention);
  assert.equal(planned.byModel, bench.byModel);
  assert.equal(planned.meanF1, bench.meanF1);
  assert.equal(planned.awaiting, bench.awaiting);
  assert.equal(planned.needAttention, bench.needAttention);
  for (const key of STEP_KEYS.filter(key => key !== "responses")) assert.equal(planned.steps[key], bench.steps[key]);
  assert.deepEqual(planned.models, ["historical-model", "test-model-a", "integrated-response-abc", "test-model-b"]);
  assert.deepEqual(planned.cases[0].missing, [c.missing[0], { caseId: "Case1", itemId: "Case1", model: "test-model-b", trial: 1 }]);
  assert.deepEqual([planned.steps.responses.done, planned.steps.responses.total, planned.steps.responses.failed, planned.steps.responses.dot], [1, 2, 0, "model"]);
});

const route = (reasoning?: string): ResponseRoute => ({ backend: "openrouter", model: "test/model-a", kwargs: reasoning ? { reasoning_effort: reasoning } : {} });
const currentTeam: ApiModelTeam = { models: ["test/model-a"], integrator: "", modelReasoning: { "test/model-a": "low" } };

test("a changed reasoning setting requires new collection without labeling a failure with the saved setting preserved", () => {
  const saved = response("Case1", "Case1", "test-model-a", 1);
  saved.row.route = route("high");
  const bench = benchmark([caseStatus("Case1", ["Case1"], [saved])]);
  const before = structuredClone(bench);
  const result = apiResponseRows(bench, currentTeam)[0];
  assert.deepEqual([result.status, result.completed, result.failed, result.pending], ["Different settings", 0, 0, 1]);
  assert.match(result.mismatch!, /Stored response reasoning is high; current setup uses low/);
  const planned = withApiResponseModels(bench, currentTeam);
  assert.deepEqual([planned.steps.responses.done, planned.steps.responses.failed, planned.steps.responses.dot], [0, 0, "none"]);
  assert.deepEqual(bench, before);
  assert.equal(bench.cases[0].responses[0].row.response, "Synthetic response");
});

const defaultTeam: ApiModelTeam = { models: ["test/model-a"], integrator: "" };
const ROUTE_CASES: { label: string; route?: ResponseRoute; inference?: Record<string, unknown>; team: ApiModelTeam; status?: string; mismatch?: RegExp }[] = [
  { label: "low route, low setup", route: route("low"), team: currentTeam, status: "Complete" },
  { label: "low route, Model default setup", route: route("low"), team: defaultTeam, mismatch: /current setup uses Model default/ },
  { label: "default route, Model default setup", route: route(), team: defaultTeam, status: "Complete" },
  { label: "default route, low setup", route: route(), team: currentTeam, mismatch: /reasoning is Model default; current setup uses low/ },
  { label: "explicit none route, Model default setup", route: route("none"), team: defaultTeam, status: "Different settings" },
  { label: "no route and no declaration", team: currentTeam, status: "Complete" },
  { label: "no route, binding_version 1 declaration", inference: { binding_version: 1, model_routes: { "test/model-a": route("high") } }, team: currentTeam, status: "Complete" },
  { label: "no route, binding_version 2 declaration", inference: { binding_version: 2, model_routes: { "test/model-a": route("high") } }, team: currentTeam, status: "Different settings" },
  { label: "per-record route overrides the declaration", route: route("low"), inference: { binding_version: 2, model_routes: { "test/model-a": route("high") } }, team: currentTeam, status: "Complete" },
  { label: "codex route stays readable", route: { backend: "codex", model: "test/model-a", kwargs: { reasoning_effort: "low" } }, inference: { binding_version: 2, model_routes: { "test/model-a": route("high") } }, team: currentTeam, mismatch: /Stored response route codex/ },
  { label: "unrelated temperature parameter", route: { ...route("low"), kwargs: { reasoning_effort: "low", temperature: 0 } }, team: currentTeam, status: "Complete" },
  { label: "null reasoning, Model default setup", route: { ...route("low"), kwargs: { reasoning_effort: null, temperature: 0 } }, team: defaultTeam, status: "Complete" },
  { label: "null reasoning, low setup", route: { ...route("low"), kwargs: { reasoning_effort: null, temperature: 0 } }, team: currentTeam, status: "Different settings" },
];

test("stored route versus current setup", () => eachCase(ROUTE_CASES, (c) => c.label, (c) => {
  const saved = response("Case1", "Case1", "test-model-a", 1);
  if (c.route) saved.row.route = c.route;
  const status = caseStatus("Case1", ["Case1"], [saved]);
  if (c.inference) status.page.provenance.inference = c.inference;
  const result = apiResponseRows(benchmark([status]), c.team)[0];
  if (c.status) assert.equal(result.status, c.status);
  if (c.mismatch) assert.match(result.mismatch!, c.mismatch);
}));

test("the reader preserves the selected response route for API coverage checks", () => {
  const fixture = buildFixture();
  writeCasesetFile(fixture, "results/responses/test-model-a.jsonl", [
    { id: "Test002", trial: 1, response: null, error: "previous failure", route: route("low") },
    { id: "Test002", trial: 1, response: "Saved successful response", route: route("high") },
  ].map(row => JSON.stringify(row)).join("\n") + "\n");
  const bench = loadBenchmark(fixture.root, CASESET);
  const selected = bench.cases[0].responses.find(({ row }) => row.model === "test-model-a")!;
  assert.deepEqual(selected.row.route, route("high"));
  assert.equal(selected.row.responseError, null);
  const result = apiResponseRows(bench, currentTeam)[0];
  assert.equal(result.status, "Different settings");
  assert.match(result.mismatch!, /reasoning is high; current setup uses low/);
});

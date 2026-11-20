import assert from "node:assert/strict";
import test from "node:test";

import { loadBenchmark } from "../lib/caseset/metrics";
import { agentPrompt, TEXT_V2_DRAFT_GUIDANCE } from "../lib/caseset/prompts";
import { datasetRedirect, keyTarget, navigationParams, relativeTime, resolveStepParams, runsRedirect, stepHref } from "../lib/caseset/routes";
import { stepForRoute } from "../lib/caseset/steps";
import { eachCase } from "./cases";
import { addReviewed, buildFixture, CASESET, MODEL_A, MODEL_B, REVIEWED_FILE, TABLE, writeCasesetFile } from "./caseset-fixture";

type PromptKey = Parameters<typeof agentPrompt>[0];
// scoped: the prompt names the case and the selected project. checks: [case, project, pattern] on agentPrompt(key, case, project).
const PROMPTS: Array<{ key: PromptKey; scoped: boolean; checks: Array<[string | undefined, string | undefined, RegExp]> }> = [
  { key: "create", scoped: false, checks: [] },
  { key: "import", scoped: false, checks: [[undefined, "alpha", /into the alpha project\./]] },
  { key: "rubrics", scoped: true, checks: [] },
  { key: "responses", scoped: true, checks: [] },
  { key: "autograding", scoped: true, checks: [[undefined, undefined, /Preserve the selected rubric format and the judge rules pinned for the project/]] },
  { key: "scores", scoped: false, checks: [
    [undefined, undefined, /^Compute scores for the project\./],
    [undefined, "beta", /^Compute scores for the beta project\./],
    [undefined, undefined, /error severities and bounds.*legacy answer tables/],
  ] },
  { key: "fixRubric", scoped: true, checks: [[undefined, undefined, /preserve the failed draft.*keep its selected rubric format.*fresh run slot/]] },
  { key: "fixAutograding", scoped: true, checks: [] },
  { key: "staleAutograding", scoped: true, checks: [] },
  { key: "useReviewedRubric", scoped: true, checks: [["Test003", undefined, /item Test003.*fresh project\/run.*reviewed rubric/]] },
];

test("agent prompts", async () => {
  await eachCase(PROMPTS, (c) => c.key, (c) => {
    assert.doesNotMatch(agentPrompt(c.key, "Test003"), /python|\.venv|--|noharm\.py|\u2014/);
    if (c.scoped) {
      assert.match(agentPrompt(c.key, "Test003"), /item Test003/);
      assert.match(agentPrompt(c.key, "Test003", "alpha"), /in the alpha project/);
    }
    for (const [caseId, project, pattern] of c.checks) assert.match(agentPrompt(c.key, caseId, project), pattern);
  });
  // Rubric prompts carry the shared draft guidance, which creates current rubrics.
  assert.ok(agentPrompt("rubrics", "Test003").includes(TEXT_V2_DRAFT_GUIDANCE));
  assert.ok(agentPrompt("rubrics").includes(TEXT_V2_DRAFT_GUIDANCE));
  const draft = agentPrompt("rubrics", "Test003", "alpha");
  assert.ok(draft.includes(TEXT_V2_DRAFT_GUIDANCE));
  for (const term of ["current text rubric format", "C1 usual care", "C2 follow-up", "Cn.0 omission", "addOn: true", "Clinical Appropriateness", "Error Severity"]) assert.ok(draft.includes(term));
});

// Each row is a call, written out as its label, and the link or step it must return.
const LINKS: Array<[string, () => string | null, string | null]> = [
  // Links keep every identifying value, in a fixed order, encoded.
  ['stepHref("autograding", { trial: 2, model: MODEL_A, item: "Test002-1", case: "Test002", version: null })', () => stepHref("autograding", { trial: 2, model: MODEL_A, item: "Test002-1", case: "Test002", version: null }), `/noharm/autograding?case=Test002&item=Test002-1&model=${MODEL_A}&trial=2`],
  ['stepHref("framework")', () => stepHref("framework"), "/noharm/framework"],
  ['stepHref("rubrics", { case: "Card 002", version: "" })', () => stepHref("rubrics", { case: "Card 002", version: "" }), "/noharm/rubrics?case=Card+002"],
  // Keys move between steps and keep the case.
  ['keyTarget("ArrowRight", "/", {})', () => keyTarget("ArrowRight", "/", {}), "/noharm/dataset"],
  ['keyTarget("ArrowRight", "/rubrics", { case: "Test002" })', () => keyTarget("ArrowRight", "/rubrics", { case: "Test002" }), "/noharm/responses?case=Test002"],
  ['keyTarget("ArrowLeft", "/cases", { case: "Test002" })', () => keyTarget("ArrowLeft", "/cases", { case: "Test002" }), "/noharm/welcome"],
  ['keyTarget("ArrowRight", "/scores", {})', () => keyTarget("ArrowRight", "/scores", {}), "/noharm/leaderboard"],
  ['keyTarget("ArrowRight", "/leaderboard", {})', () => keyTarget("ArrowRight", "/leaderboard", {}), null],
  ['keyTarget("ArrowLeft", "/leaderboard", { case: "Test002" })', () => keyTarget("ArrowLeft", "/leaderboard", { case: "Test002" }), "/noharm/scores?case=Test002"],
  ['keyTarget("6", "/framework", { case: "Test002" })', () => keyTarget("6", "/framework", { case: "Test002" }), "/noharm/leaderboard"],
  ['stepHref("leaderboard", { case: "Test002", model: MODEL_A })', () => stepHref("leaderboard", { case: "Test002", model: MODEL_A }), "/noharm/leaderboard"],
  ['keyTarget("3", "/framework", {})', () => keyTarget("3", "/framework", {}), "/noharm/responses"],
  ['keyTarget("d", "/scores", { case: "Test002" })', () => keyTarget("d", "/scores", { case: "Test002" }), "/noharm/dashboard"],
  ['keyTarget("x", "/", {})', () => keyTarget("x", "/", {}), null],
  // Never leave the editor mid-edit.
  ['keyTarget("ArrowRight", "/review", { case: "Test002" })', () => keyTarget("ArrowRight", "/review", { case: "Test002" }), null],
  ['keyTarget("6", "/review", { case: "Test002" })', () => keyTarget("6", "/review", { case: "Test002" }), null],
  // Old run viewer links redirect without losing their target.
  ['runsRedirect([], {})', () => runsRedirect([], {}), "/noharm/dashboard"],
  ['runsRedirect(["cs1"], { case: "Test002" })', () => runsRedirect(["cs1"], { case: "Test002" }), "/noharm/dataset?case=Test002"],
  ['runsRedirect(["cs1", "Test002", "table", "reviewed-dwu"], {})', () => runsRedirect(["cs1", "Test002", "table", "reviewed-dwu"], {}), "/noharm/review?case=Test002&version=reviewed-dwu"],
  ['runsRedirect(["cs1", "Test002-1", "response", MODEL_A, "2"], {})', () => runsRedirect(["cs1", "Test002-1", "response", MODEL_A, "2"], {}), `/noharm/autograding?case=Test002&item=Test002-1&model=${MODEL_A}&trial=2`],
  // Dataset navigation accepts canonical and legacy routes without changing stored keys.
  ['stepForRoute("dataset")', () => stepForRoute("dataset"), "cases"],
  ['stepForRoute("inputs")', () => stepForRoute("inputs"), "cases"],
  ['stepForRoute("cases")', () => stepForRoute("cases"), "cases"],
  ['stepForRoute("unknown")', () => stepForRoute("unknown"), null],
  ['stepHref("cases", { case: "Test002", item: "Test002-1", trial: 2 })', () => stepHref("cases", { case: "Test002", item: "Test002-1", trial: 2 }), "/noharm/dataset?case=Test002&item=Test002-1&trial=2"],
  ['keyTarget("ArrowRight", "/dataset", { case: "Test002" })', () => keyTarget("ArrowRight", "/dataset", { case: "Test002" }), "/noharm/rubrics?case=Test002"],
  ['keyTarget("ArrowRight", "/inputs", { case: "Test002" })', () => keyTarget("ArrowRight", "/inputs", { case: "Test002" }), "/noharm/rubrics?case=Test002"],
  ['keyTarget("ArrowRight", "/cases", { case: "Test002" })', () => keyTarget("ArrowRight", "/cases", { case: "Test002" }), "/noharm/rubrics?case=Test002"],
  ['keyTarget("ArrowLeft", "/dataset", {})', () => keyTarget("ArrowLeft", "/dataset", {}), "/noharm/welcome"],
  ['keyTarget("1", "/scores", {})', () => keyTarget("1", "/scores", {}), "/noharm/dataset"],
  ['datasetRedirect({ case: "Card 002", item: "Card002-1", trial: "2", tag: ["a", "b"], missing: undefined })', () => datasetRedirect({ case: "Card 002", item: "Card002-1", trial: "2", tag: ["a", "b"], missing: undefined }), "/noharm/dataset?case=Card+002&item=Card002-1&trial=2&tag=a&tag=b"],
  ['datasetRedirect({})', () => datasetRedirect({}), "/noharm/dataset"],
];

test("step links, keys, and redirects", () => eachCase(LINKS, ([label]) => label, ([, call, expected]) => {
  assert.equal(call(), expected);
}));

test("resolveStepParams fallbacks and addressable missing answers", () => {
  // Step parameters fall back to the first case, the rubric autograding used, the base item, the first model, and trial 1.
  const fixture = buildFixture();
  const b = loadBenchmark(fixture.root, CASESET);
  assert.deepEqual(resolveStepParams(b, {}), { caseId: "Test002", version: "run1", itemId: "Test002", model: MODEL_A, trial: 1 });
  assert.deepEqual(resolveStepParams(b, { case: "Nope", version: "run9", model: "x", trial: "7" }), { caseId: "Test002", version: "run1", itemId: "Test002", model: MODEL_A, trial: 1 });
  assert.deepEqual(resolveStepParams(b, { version: "run2", model: MODEL_B, trial: "1" }), { caseId: "Test002", version: "run2", itemId: "Test002", model: MODEL_B, trial: 1 });
  assert.equal(resolveStepParams(b, { model: MODEL_A, trial: "2" })?.trial, 2);
  // A missing answer's item and trial stay addressable.
  writeCasesetFile(fixture, "provenance.json", { trials: 2 });
  writeCasesetFile(fixture, "items.jsonl", `${JSON.stringify({ id: "Test002", prompt: "p", metadata: { base_id: "Test002" } })}\n${JSON.stringify({ id: "Test002-1", prompt: "p1", metadata: { base_id: "Test002" } })}\n`);
  const variant = loadBenchmark(fixture.root, CASESET);
  assert.deepEqual(resolveStepParams(variant, { item: "Test002-1", model: MODEL_A, trial: "2" }), { caseId: "Test002", version: "run1", itemId: "Test002-1", model: MODEL_A, trial: 2 });
});

test("Rubrics step default version", () => {
  // Rubrics opens the latest passing draft while results retain their bound rubric.
  const fixture = buildFixture();
  addReviewed(fixture);
  let bench = loadBenchmark(fixture.root, CASESET);
  assert.equal(resolveStepParams(bench, {}, "rubrics")?.version, "run3");
  assert.equal(resolveStepParams(bench, { version: "run1" }, "rubrics")?.version, "run1");
  assert.equal(resolveStepParams(bench, { version: "run2" }, "rubrics")?.version, "run2");
  assert.equal(resolveStepParams(bench, { version: "reviewed-dwu" }, "rubrics")?.version, "reviewed-dwu");
  assert.equal(resolveStepParams(bench, {}, "autograding")?.version, "run1");
  assert.equal(resolveStepParams(bench, {}, "scores")?.version, "run1");
  writeCasesetFile(fixture, "answer-tables/Test002.run10.json", TABLE);
  writeCasesetFile(fixture, "answer-tables/Test002.run10.status.json", { status: "pass", errors: [] });
  writeCasesetFile(fixture, "answer-tables/Test002.run11.json", TABLE);
  writeCasesetFile(fixture, "answer-tables/Test002.run11.status.json", { status: "failed", errors: ["incomplete"] });
  bench = loadBenchmark(fixture.root, CASESET);
  assert.equal(resolveStepParams(bench, {}, "rubrics")?.version, "run10");

  // Rubrics preserves a reviewed copy based on the latest passing draft.
  const based = buildFixture();
  const latest = loadBenchmark(based.root, CASESET).cases[0].page.tables.find((t) => t.version === "run3")!;
  writeCasesetFile(based, "answer-tables/Test002.reviewed-dwu.json", {
    ...REVIEWED_FILE, basedOn: { version: latest.version, sha256: latest.sha256 },
  });
  writeCasesetFile(based, "answer-tables/Test002.reviewed-dwu.status.json", { status: "pass", errors: [] });
  assert.equal(resolveStepParams(loadBenchmark(based.root, CASESET), {}, "rubrics")?.version, "reviewed-dwu");
});

test("stage navigation preserves the selected response and rubric for sidebar and keyboard links", () => {
  const search = new URLSearchParams({ case: "Test002", version: "reviewed-dwu", item: "Test002-1", model: MODEL_B, trial: "2", unrelated: "ignored" });
  const params = navigationParams(search);
  const query = `case=Test002&version=reviewed-dwu&item=Test002-1&model=${MODEL_B}&trial=2`;
  assert.equal(stepHref("scores", params), `/noharm/scores?${query}`);
  assert.equal(keyTarget("ArrowRight", "/autograding", params), `/noharm/scores?${query}`);
  assert.equal(keyTarget("3", "/scores", params), `/noharm/responses?${query}`);
  assert.equal(keyTarget("ArrowLeft", "/autograding", params), `/noharm/responses?${query}`);
  assert.equal(stepHref("rubrics", params), `/noharm/rubrics?${query}`);
  assert.equal(keyTarget("6", "/scores", params), "/noharm/leaderboard");
  assert.equal(stepHref("cases", navigationParams(new URLSearchParams())), "/noharm/dataset");
  const fixture = buildFixture();
  addReviewed(fixture);
  writeCasesetFile(fixture, "provenance.json", { trials: 2 });
  writeCasesetFile(fixture, "items.jsonl", `${JSON.stringify({ id: "Test002-1", prompt: "p1", metadata: { base_id: "Test002" } })}\n`);
  const destination = resolveStepParams(loadBenchmark(fixture.root, CASESET), Object.fromEntries(new URLSearchParams(stepHref("scores", params).split("?")[1])));
  assert.equal(destination?.itemId, "Test002-1");
  assert.equal(destination?.model, MODEL_B);
  assert.equal(destination?.trial, 2);
  assert.equal(destination?.version, "reviewed-dwu");
});

test("relative time reads in minutes, hours, and days", () => {
  const now = new Date("2026-09-29T12:00:00Z");
  assert.equal(relativeTime("2026-09-29T11:58:00Z", now), "2 min ago");
  assert.equal(relativeTime("2026-09-29T09:00:00Z", now), "3 h ago");
  assert.equal(relativeTime("2026-09-26T12:00:00Z", now), "3 days ago");
  assert.equal(relativeTime("2026-09-29T11:59:50Z", now), "just now");
  assert.equal(relativeTime(null, now), "at an unknown time");
});



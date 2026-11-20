import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { validateAnswerTable } from "../lib/answer-table";
import { buildLeaderboard } from "../lib/caseset/leaderboard";
import { loadBenchmark, listBenchmarks } from "../lib/caseset/metrics";
import { tutorialBenchmark, tutorialDataset, tutorialRubric, TUTORIAL_CASE, TUTORIAL_PROJECT } from "../lib/uti-tutorial-benchmark";
import { datasetFields } from "../lib/dataset-fields";

const root = fileURLToPath(new URL("../../projects/", import.meta.url));

test("bundled demo and walkthrough match exactly and keep clinical-review safeguards", () => {
  assert.ok(listBenchmarks(root).includes("demo"));
  const demo = loadBenchmark(root, "demo");
  const walkthrough = tutorialBenchmark();
  assert.deepEqual(walkthrough, {
    ...demo,
    name: TUTORIAL_PROJECT,
    cases: demo.cases.map((item) => ({ ...item, page: { ...item.page, caseset: TUTORIAL_PROJECT } })),
  });
  assert.deepEqual(demo.cases.map((item) => item.caseId), [TUTORIAL_CASE]);
  const tables = demo.cases[0].page.tables;
  assert.deepEqual(tables.map((table) => table.version), ["run2"]);
  assert.deepEqual(tutorialRubric(), tables[0].record);
  assert.deepEqual(validateAnswerTable(tutorialRubric()), []);
  const fields = datasetFields(demo.cases[0].page.source);
  const example = tutorialDataset();
  assert.equal(fields.task, example.task);
  assert.deepEqual(fields.solutions, [example.solution, example.alternative]);
  assert.equal(fields.errors, example.errors);
  assert.deepEqual(Object.values(demo.steps).map((step) => [step.key, step.done, step.total]), [
    ["cases", 1, 1], ["rubrics", 1, 1], ["responses", 3, 3],
    ["autograding", 3, 3], ["scores", 3, 3], ["leaderboard", 3, 3],
  ]);
  assert.equal(demo.awaiting.rubrics, 1);
  assert.equal(demo.awaiting.autograding, 3);
  assert.equal(demo.needAttention, 0);
  assert.equal(demo.cases[0].page.provenance.synthetic, true);
  for (const response of demo.cases[0].responses) {
    assert.equal(response.row.judge, "pass");
    assert.equal(response.row.scoreCheck, "current");
    assert.equal(response.row.record!.rubric, "run2");
    assert.equal(response.scoreReviewed, false);
  }
  assert.deepEqual(buildLeaderboard(tutorialBenchmark()), buildLeaderboard(demo));
  assert.deepEqual(buildLeaderboard(demo).map((row) => [row.model, row.worstHarm, row.draft, row.unverified]), [
    ["Model-A", "none", true, false],
    ["Model-C", "none", true, false],
    ["Model-B", "severe", true, false],
  ]);
});

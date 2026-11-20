import assert from "node:assert/strict";
import test from "node:test";
import { TUTORIAL_STAGES } from "../lib/uti-tutorial";
import { tutorialBenchmark, tutorialDataset, tutorialRubric, TUTORIAL_PROJECT, TUTORIAL_CASE } from "../lib/uti-tutorial-benchmark";
import { validateAnswerTable, validRecommendationTags, type AnswerTableCase } from "../lib/answer-table";
import { scoreAnswerTable } from "../lib/answer-score";
import { GET, PUT } from "../app/api/runs/table/route";
import { NextRequest } from "next/server";

test("prepared mappings quote the stored responses, use current rubric option identities, and map Model C to the conditional antibiotic", () => {
  const rubric = tutorialRubric();
  const decisions = new Map(rubric.decisions.map((decision) => [decision.id, decision]));
  for (const response of tutorialBenchmark().cases[0].responses) {
    const judge = response.row.record!.judge!;
    assert.deepEqual(Object.keys(judge.decisions), [...decisions.keys()]);
    for (const [id, output] of Object.entries(judge.decisions)) {
      for (const recommended of output.recommended ?? []) {
        assert.ok(response.row.response!.includes(recommended.evidence));
        const option = decisions.get(id)!.recommendations.find((option) => option.id === recommended.rowId);
        assert.ok(option);
        if (option.parts) assert.deepEqual(recommended.partsPresent, option.parts);
      }
    }
  }
  assert.deepEqual(TUTORIAL_STAGES.map((stage) => stage.key), ["dataset", "rubrics", "responses", "autograding", "scores", "leaderboard"]);
  const bench = tutorialBenchmark();
  assert.deepEqual(bench.models, ["Model-A", "Model-B", "Model-C"]);
  const modelC = bench.cases[0].responses.find((response) => response.row.model === "Model-C")!.row.record!.judge!;
  assert.equal(modelC.decisions.D4.recommended![0].rowId, "D4.O2");
  assert.deepEqual(modelC.decisions.D4.recommended![0].partsPresent, rubric.decisions[3].recommendations[1].parts);
  assert.equal(modelC.decisions.D7.recommended!.length, 0);
});

test("tutorial scores are recomputed from the same rated draft and stored judgments", () => {
  const record = tutorialRubric();
  assert.deepEqual(validateAnswerTable(record), []);
  assert.equal(record.usualCare.harm, "severe");
  assert.equal(record.decisions.length, 7);
  const bench = tutorialBenchmark();
  for (const response of bench.cases[0].responses) {
    const result = scoreAnswerTable(record, response.row.record!.judge as Parameters<typeof scoreAnswerTable>[1]);
    for (const key of ["f1", "recall", "precision", "worstHarm"] as const) {
      assert.deepEqual(response.row.scored![key], result[key]);
    }
    assert.equal(response.scoreReviewed, false);
  }
});

test("tutorial editor loads the canonical rubric read-only and refuses saves and other versions", async () => {
  const response = await GET(new NextRequest(`http://localhost:9000/api/runs/table?caseset=${TUTORIAL_PROJECT}&caseId=${TUTORIAL_CASE}&version=run2`));
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.record.usualCare.harm, "severe");
  assert.deepEqual(payload.errors, []);
  assert.equal(payload.canSave, false);
  const options = (payload.record as AnswerTableCase).decisions.flatMap((decision) => decision.recommendations);
  assert.equal(options.length, 17);
  for (const option of options) {
    assert.ok(option.tags?.length, `${option.id} needs an action tag`);
    assert.ok(validRecommendationTags(option.tags), `${option.id} has invalid tags`);
  }
  assert.deepEqual(options.find((option) => option.id === "D1.O1")?.tags, ["followUp"]);
  assert.deepEqual(options.find((option) => option.id === "D6.O1")?.tags, ["diagnostic", "none"]);
  assert.deepEqual(options.find((option) => option.id === "D7.O1")?.tags, ["medication", "none"]);
  const benchmark = tutorialBenchmark();
  const table = benchmark.cases[0].page.tables[0];
  assert.deepEqual(table.record, payload.record);
  assert.deepEqual(benchmark.cases[0].page.source, payload.source);
  assert.deepEqual(table.ratings, payload.ratings);
  assert.equal(table.status, payload.status);
  assert.equal(table.sha256, payload.sourceSha256);
  for (const stored of benchmark.cases[0].responses) {
    assert.equal(stored.row.record?.rubric_sha256, payload.sourceSha256);
    assert.equal(stored.row.scored?.rubric_sha256, payload.sourceSha256);
    assert.equal(stored.row.scoreCheck, "current");
  }
  assert.deepEqual(payload.record, tutorialRubric());
  assert.ok(payload.source.recommendations.includes(tutorialDataset().alternative));
  for (const [caseId, version] of [[TUTORIAL_CASE, "run1"], ["missing", "run2"]]) {
    const archived = await GET(new NextRequest(`http://localhost/api/runs/table?caseset=${TUTORIAL_PROJECT}&caseId=${caseId}&version=${version}`));
    assert.equal(archived.status, 404);
  }
  const save = await PUT(new NextRequest("http://localhost/api/runs/table", { method: "PUT", body: JSON.stringify({ caseset: TUTORIAL_PROJECT }) }));
  assert.equal(save.status, 400);
  assert.match((await save.json()).error, /practice only/);
});

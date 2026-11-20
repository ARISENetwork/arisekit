import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { POST } from "../app/api/dataset-case/route";
import { caseHasResults, datasetOutdated, saveDatasetCase } from "../lib/dataset-edit";
import { loadCasePage } from "../lib/caseset/read";
import { caseEdits } from "../lib/dataset-outdated";
import { addReviewed, buildFixture, CASESET, MODEL_A, MODEL_B, RESPONSE, TABLE, writeCasesetFile } from "./caseset-fixture";
import { datasetFields } from "../lib/dataset-fields";

function fixture(): { root: string; dir: string; basis: ReturnType<typeof datasetFields> } {
  const root = mkdtempSync(path.join(os.tmpdir(), "dataset-edit-"));
  const dir = path.join(root, "test");
  mkdirSync(path.join(dir, "cases"), { recursive: true });
  writeFileSync(path.join(dir, "cases/Case001.json"), JSON.stringify({ presentation: "Original task", recommendations: "Original solution", errors: "Original error", source_provenance: { source_file: "/original/upload.json" } }));
  writeFileSync(path.join(dir, "items.jsonl"), JSON.stringify({ id: "Case001", prompt: "Original task", metadata: { base_id: "Case001" } }) + "\n");
  return { root, dir, basis: { task: "Original task", solutions: ["Original solution"], errors: "Original error" } };
}

test("edits an unused case under the same ID, preserving its source and syncing the model input; other cases' results do not lock it", () => {
  const { root, dir, basis } = fixture();
  const original = readFileSync(path.join(dir, "cases/Case001.json"));
  const value = { task: "Updated task", solutions: ["Answer A", "Answer B"], errors: "Updated error" };
  saveDatasetCase(root, "test", "Case001", value, basis);
  const source = JSON.parse(readFileSync(path.join(dir, "cases/Case001.json"), "utf8"));
  assert.deepEqual(datasetFields(source), value);
  assert.equal(JSON.parse(readFileSync(path.join(dir, "items.jsonl"), "utf8")).prompt, value.task);
  assert.match(source.recommendations, /Acceptable solution 1:\nAnswer A/);
  assert.match(source.recommendations, /Author-provided error criteria/);
  assert.equal(source.source_provenance.source_file, "/original/upload.json");
  assert.match(source.source_provenance.prior_source, /^cases\/history\/Case001\/[0-9a-f-]{36}\/source\.json$/);
  assert.deepEqual(readFileSync(path.join(dir, source.source_provenance.prior_source)), original);
  const before = readdirSync(path.join(dir, "cases/history/Case001"));
  saveDatasetCase(root, "test", "Case001", value, value);
  assert.deepEqual(readdirSync(path.join(dir, "cases/history/Case001")), before);
  assert.throws(() => saveDatasetCase(root, "test", "Case001", basis, basis), /changed while/);

  // Another case's results do not lock an unused case.
  const other = fixture();
  mkdirSync(path.join(other.dir, "answer-tables"));
  writeFileSync(path.join(other.dir, "answer-tables/Case002.run1.json"), "{}");
  mkdirSync(path.join(other.dir, "results/responses"), { recursive: true });
  writeFileSync(path.join(other.dir, "results/responses/model.jsonl"), '{"id":"Case002","response":"Answer"}\n');
  assert.equal(caseHasResults(other.dir, "Case001"), false);
  saveDatasetCase(other.root, "test", "Case001", { ...other.basis, task: "Changed" }, other.basis);
});

test("editing a case with results keeps them and tags those made before the edit", () => {
  const fixture = buildFixture();
  addReviewed(fixture);
  const source = JSON.parse(readFileSync(path.join(fixture.dir, "cases/Test002.json"), "utf8"));
  const basis = datasetFields(source);
  assert.equal(caseHasResults(fixture.dir, "Test002"), true);
  const before = readdirSync(path.join(fixture.dir, "answer-tables")).map((file) => [file, readFileSync(path.join(fixture.dir, "answer-tables", file), "utf8")]);
  saveDatasetCase(fixture.root, CASESET, "Test002", { ...basis, solutions: ["Refer to cardiology."] }, basis);
  let page = loadCasePage(fixture.root, CASESET, "Test002");
  assert.deepEqual(Object.fromEntries(page.tables.map((t) => [t.version, t.outdated])), { run1: "solution", run2: "solution", run3: "solution", "reviewed-dwu": "solution" });
  assert.deepEqual(page.responses.map((r) => r.outdated), [undefined, undefined, undefined]);
  assert.deepEqual(datasetOutdated(page), { rubric: "solution", responses: 0 });
  assert.deepEqual(readdirSync(path.join(fixture.dir, "answer-tables")).map((file) => [file, readFileSync(path.join(fixture.dir, "answer-tables", file), "utf8")]), before);

  const solutionEdit = datasetFields(page.source);
  saveDatasetCase(fixture.root, CASESET, "Test002", { ...solutionEdit, task: "A 68-year-old man with palpitations." }, solutionEdit);
  page = loadCasePage(fixture.root, CASESET, "Test002");
  assert.equal(page.tables.find((t) => t.version === "run1")?.outdated, "task");
  assert.deepEqual(page.responses.map((r) => [r.model, r.trial, r.outdated, r.judge]), [[MODEL_A, 1, "task", "stale"], [MODEL_A, 2, "task", "no response"], [MODEL_B, 1, "task", "stale"]]);
  assert.deepEqual(caseEdits(page.source).map((edit) => edit.changed), [["solutions"], ["task"]]);

  writeCasesetFile(fixture, "answer-tables/Test002.run4.json", TABLE);
  writeCasesetFile(fixture, "answer-tables/Test002.run4.status.json", { status: "pass", errors: [] });
  writeCasesetFile(fixture, "answer-tables/Test002.run1.json", { ...TABLE, harmOverrides: false });
  page = loadCasePage(fixture.root, CASESET, "Test002");
  assert.equal(page.tables.find((t) => t.version === "run4")?.outdated, undefined);
  assert.equal(page.tables.find((t) => t.version === "run1")?.outdated, undefined, "a rewritten rubric file is not the one that existed at the edit");
  assert.equal(page.tables.find((t) => t.version === "reviewed-dwu")?.outdated, "task");
  assert.deepEqual(datasetOutdated(page), { rubric: null, responses: 2 });
});

test("save API rejects foreign origins and conflicting saves", async () => {
  const { root, dir, basis } = fixture();
  const previous = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = root;
  try {
    const body = JSON.stringify({ project: "test", id: "Case001", value: { ...basis, task: "Changed" }, basis });
    const request = (origin?: string): NextRequest => new NextRequest("http://localhost/api/dataset-case", { method: "POST", headers: { "Content-Type": "application/json", ...(origin ? { origin } : {}) }, body });
    assert.equal((await POST(request("http://elsewhere"))).status, 403);
    assert.equal((await POST(request())).status, 200);
    assert.equal((await POST(request())).status, 409);
    assert.equal(JSON.parse(readFileSync(path.join(dir, "cases/Case001.json"), "utf8")).presentation, "Changed");
  } finally { if (previous === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = previous; }
});

test("a response re-collected for the edited Task is current even when its text matches the earlier answer", () => {
  const fixture = buildFixture();
  const responses = path.join(fixture.dir, "results", "responses", `${MODEL_B}.jsonl`);
  const row = (binding: string): string => JSON.stringify({ id: "Test002", trial: 1, response: RESPONSE, input_sha256: binding }) + "\n";
  writeFileSync(responses, row("earlier-task-input"));
  const basis = datasetFields(JSON.parse(readFileSync(path.join(fixture.dir, "cases/Test002.json"), "utf8")));
  saveDatasetCase(fixture.root, CASESET, "Test002", { ...basis, task: "A 68-year-old man with palpitations." }, basis);
  const modelB = (): string | undefined => loadCasePage(fixture.root, CASESET, "Test002").responses.find((r) => r.model === MODEL_B)?.outdated;
  assert.equal(modelB(), "task", "the response that existed at the edit is out of date");
  assert.deepEqual(caseEdits(loadCasePage(fixture.root, CASESET, "Test002").source).at(-1)?.responses.find((r) => r.model === MODEL_B)?.input_sha256, "earlier-task-input");
  writeFileSync(responses, row("edited-task-input"));
  assert.equal(modelB(), undefined, "the same text collected for the edited Task is current");
});

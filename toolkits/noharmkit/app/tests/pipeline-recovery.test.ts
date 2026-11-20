import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { NextRequest } from "next/server";
import { POST as forkApi } from "../app/api/pipeline/recovery/route";
import { filesIn } from "../lib/project-files";
import { saveApiPipelineConfig } from "../lib/api-pipeline-store";
import type { ApiPipelineConfig } from "../lib/api-pipeline-config";
import { createProject } from "../lib/project-create";
import { currentPipelineRun, executePipeline, pipelinePython, type PipelineRunRecord } from "../lib/pipeline-runner";
import { inspectRecovery, mergeRetainedFiles, newRecoveryRun, requireRecoveryTicket, restoreRecovery } from "../lib/pipeline-recovery";
import { localPipelineWorkspace, materializeProject, readPipelineRecord, writePipelineRecord } from "../lib/pipeline-workspace";
import { fileHashes, projectFingerprint, readWorkspaceState, updateWorkspaceWorker } from "../lib/pipeline-workspace-state";

const config: ApiPipelineConfig = { version: 1, generationModel: "fixture/writer", ratingModels: [], responseModels: ["fixture/model"], judgeModel: "fixture/judge" };
const inspect = async () => ({ status: "ready" as const, operationIdentity: "operation-one", reusableCalls: 1, pending: true });
const encoded = (text: string): string => Buffer.from(text).toString("base64");

function fixture() {
  const root = mkdtempSync(path.join(os.tmpdir(), "recovery-test-"));
  const project = "example";
  createProject(root, project, "", "api");
  saveApiPipelineConfig(root, project, config);
  const workspace = localPipelineWorkspace(root, project);
  return { root, project, workspace, directory: path.join(root, project) };
}

async function interrupted() {
  const f = fixture();
  const record: PipelineRunRecord = { jobId: "12345678-1234-1234-1234-123456789abc", action: { stage: "responses" }, config, status: "interrupted", startedAt: new Date().toISOString(), finishedAt: new Date().toISOString(), message: "Connection interrupted", executionDirectory: f.workspace.directory, operationIdentity: "operation-one" };
  updateWorkspaceWorker(f.workspace.directory, f.project, f.workspace.key, record.jobId, { state: "exited" });
  writePipelineRecord(f.workspace.directory, "latest.json", record);
  writePipelineRecord(f.workspace.directory, `${record.jobId}.json`, record);
  await f.workspace.publish();
  return { ...f, record };
}

test("three-way recovery preserves independent edits, reports conflicts, and never removes files", () => {
  const base = { "source.json": encoded("source"), "old.json": encoded("old") };
  const current = { ...base, "note.txt": encoded("user note") };
  const retained = { ...base, "call.json": encoded("saved call") };
  const result = mergeRetainedFiles(current, retained, fileHashes(base));
  assert.deepEqual(result, { files: { ...current, "call.json": retained["call.json"] }, conflicts: [], restored: 1 });
  assert.deepEqual(mergeRetainedFiles({ ...current, "call.json": encoded("edited") }, retained, fileHashes(base)).conflicts, ["call.json"]);
  assert.deepEqual(mergeRetainedFiles(current, { "source.json": base["source.json"] }, fileHashes(base)).conflicts, ["old.json"]);
});

test("compatible interrupted work restores unpublished output, resumes, and preserves the old job", async () => {
  const f = await interrupted();
  const oldJob = readFileSync(path.join(f.directory, "web-execution", `${f.record.jobId}.json`));
  materializeProject(f.workspace.directory, { "results/saved.json": encoded('{"saved":true}') });
  const reviewed = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), inspect);
  assert.equal(reviewed.plan.status, "ready");
  assert.equal(reviewed.plan.restoredFiles, 1);
  const retry = localPipelineWorkspace(f.root, f.project);
  const ticket = { jobId: f.record.jobId, token: reviewed.plan.token! };
  restoreRecovery(retry, reviewed, ticket);
  const driver = path.join(retry.root, "fixture.py");
  writeFileSync(driver, "import json,sys\nfrom pathlib import Path\nr=json.loads(sys.stdin.readline())\nassert json.loads((Path(r['project'])/'results/saved.json').read_text())=={'saved':True}\nprint(json.dumps({'type':'result','status':'completed','errors':[]}))\n");
  const result = await executePipeline(retry, f.record.action, config, { inspect, recoveredFrom: f.record.jobId, apiKey: "fixture", python: pipelinePython(), driver, signal: new AbortController().signal, emit() {} });
  assert.equal(result.status, "completed");
  assert.equal(result.recoveredFrom, f.record.jobId);
  assert.deepEqual(readFileSync(path.join(f.directory, "web-execution", `${f.record.jobId}.json`)), oldJob);
  assert.deepEqual(JSON.parse(readFileSync(path.join(f.directory, "results/saved.json"), "utf8")), { saved: true });
  assert.equal(currentPipelineRun(f.directory)?.status, "completed");
});

test("changed stage identity requires a new run without publishing retained outputs", async () => {
  const f = await interrupted();
  const before = projectFingerprint(filesIn(f.directory));
  const reviewed = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), async () => ({ ...await inspect(), operationIdentity: "changed-upstream-version" }));
  assert.equal(reviewed.plan.status, "new-run");
  assert.equal(projectFingerprint(filesIn(f.directory)), before);
  assert.throws(() => restoreRecovery(localPipelineWorkspace(f.root, f.project), reviewed, { jobId: f.record.jobId, token: reviewed.plan.token! }), /cannot be resumed/);
});

test("a live or unverifiable worker blocks recovery before inspection", async () => {
  const f = await interrupted();
  for (const worker of [{ state: "running" as const, pid: process.pid }, { state: "starting" as const }]) {
    updateWorkspaceWorker(f.workspace.directory, f.project, f.workspace.key, f.record.jobId, worker);
    const reviewed = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), async () => { assert.fail("Inspection must not start while a worker may be active"); });
    assert.equal(reviewed.plan.status, "running");
    assert.equal(reviewed.plan.token, undefined);
  }
});

test("ownership mismatch and legacy records cannot import another execution's files", async () => {
  const f = await interrupted();
  const wrongOwner = await inspectRecovery(f.directory, "local:/other/project", config, pipelinePython(), inspect);
  assert.equal(wrongOwner.plan.status, "blocked");
  assert.match(wrongOwner.plan.reason, /another workspace/);
  const state = readWorkspaceState(f.workspace.directory, f.project, f.workspace.key)!;
  assert.equal(state.key, f.workspace.key);
  writePipelineRecord(f.directory, "latest.json", { ...f.record, executionDirectory: f.directory });
  const invalid = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), inspect);
  assert.equal(invalid.plan.status, "blocked");
  assert.match(invalid.plan.reason, /not a managed workspace/);
});

test("publication conflicts offer a new run and do not overwrite either version", async () => {
  const f = await interrupted();
  materializeProject(f.directory, { "results/conflict.json": encoded("user edit") });
  materializeProject(f.workspace.directory, { "results/conflict.json": encoded("retained output") });
  const sourceBefore = projectFingerprint(filesIn(f.directory)), retainedBefore = projectFingerprint(filesIn(f.workspace.directory));
  const reviewed = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), async () => { assert.fail("Conflicts must be handled before stage inspection"); });
  assert.equal(reviewed.plan.status, "new-run");
  assert.match(reviewed.plan.reason, /results\/conflict.json/);
  assert.equal(projectFingerprint(filesIn(f.directory)), sourceBefore);
  assert.equal(projectFingerprint(filesIn(f.workspace.directory)), retainedBefore);
});

test("a stale inspection ticket cannot resume after source changes", async () => {
  const f = await interrupted();
  const old = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), inspect);
  const ticket = { jobId: f.record.jobId, token: old.plan.token! };
  materializeProject(f.directory, { "note.txt": encoded("changed after inspection") });
  const latest = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), inspect);
  assert.throws(() => requireRecoveryTicket(latest, ticket), /changed after inspection/);
  assert.throws(() => restoreRecovery(localPipelineWorkspace(f.root, f.project), old, ticket), /project changed after inspection/);
});

test("a fresh judge run copies exact upstream inputs, records hashes, and keeps old results untouched", async () => {
  const f = await interrupted();
  const job = { ...f.record, action: { stage: "judge" as const, rubric: "run2" } };
  writePipelineRecord(f.directory, "latest.json", job);
  writePipelineRecord(f.workspace.directory, "latest.json", job);
  const source = {
    "cases/Case001.json": encoded('{"presentation":"Synthetic","recommendations":"Synthetic"}'),
    "answer-tables/Case001.run2.json": encoded('{"rubric":"source"}'),
    "results/responses/fixture-model.jsonl": encoded('{"response":"source"}\n'),
    "results/judge/fixture-model.jsonl": encoded('{"judge":"old"}\n'),
    "results/fixture-model_scored.jsonl": encoded('{"score":"old"}\n'),
  };
  materializeProject(f.directory, source);
  const reviewed = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), async () => ({ status: "blocked", reusableCalls: 0, reason: "Changed judging rules" }));
  assert.equal(reviewed.plan.status, "new-run");
  const before = projectFingerprint(filesIn(f.directory));
  newRecoveryRun(f.root, f.project, "example-retry", reviewed, { jobId: job.jobId, token: reviewed.plan.token! }, config);
  const copied = filesIn(path.join(f.root, "example-retry"));
  assert.equal(copied["cases/Case001.json"], source["cases/Case001.json"]);
  assert.equal(copied["answer-tables/Case001.run2.json"], source["answer-tables/Case001.run2.json"]);
  assert.equal(copied["results/responses/fixture-model.jsonl"], source["results/responses/fixture-model.jsonl"]);
  assert.equal(copied["results/judge/fixture-model.jsonl"], undefined);
  assert.equal(copied["results/fixture-model_scored.jsonl"], undefined);
  const manifest = JSON.parse(Buffer.from(copied["recovery-source.json"], "base64").toString());
  for (const [name, hash] of Object.entries(manifest.copiedFiles)) assert.equal(fileHashes(copied)[name], hash);
  assert.equal(projectFingerprint(filesIn(f.directory)), before);
});

test("recovery rejects a foreign-origin fork request before any workspace access", async () => {
  const response = await forkApi(new NextRequest("http://localhost/api/pipeline/recovery", { method: "POST", headers: { origin: "https://other.example", "Content-Type": "application/json" }, body: JSON.stringify({ project: "example" }) }));
  assert.equal(response.status, 403);
});

test("scoring recovery retains the source runtime pin, including an unpinned legacy project", async () => {
  for (const pin of [undefined, "6d803fee097fef0040a58e017053b2e88238ef60", "d734383670f0e8251f46fc3e800038f2a46db0d6"]) {
    const f = await interrupted();
    const provenancePath = path.join(f.directory, "provenance.json");
    const provenance = JSON.parse(readFileSync(provenancePath, "utf8"));
    if (pin === undefined) delete provenance.judge_scoring_source_commit;
    else provenance.judge_scoring_source_commit = pin;
    writeFileSync(provenancePath, JSON.stringify(provenance));
    const job = { ...f.record, action: { stage: "score" as const } };
    writePipelineRecord(f.directory, "latest.json", job);
    materializeProject(f.directory, { "results/judge/fixture-model.jsonl": encoded('{"judge":"source"}\n') });
    const reviewed = await inspectRecovery(f.directory, f.workspace.key, config, pipelinePython(), async () => ({ status: "blocked", reusableCalls: 0, reason: "New run required" }));
    const before = projectFingerprint(filesIn(f.directory));
    newRecoveryRun(f.root, f.project, "runtime-retry", reviewed, { jobId: job.jobId, token: reviewed.plan.token! }, config);
    const copied = JSON.parse(readFileSync(path.join(f.root, "runtime-retry", "provenance.json"), "utf8"));
    assert.equal(copied.judge_scoring_source_commit, pin);
    assert.equal(projectFingerprint(filesIn(f.directory)), before);
  }
});

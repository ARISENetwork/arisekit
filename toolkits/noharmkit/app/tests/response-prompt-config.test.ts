import assert from "node:assert/strict";
import test from "node:test";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { POST as runApi } from "../app/api/pipeline/run/route";
import { filesIn } from "../lib/project-files";
import { apiConfigImpact } from "../lib/api-config-impact";
import { forkApiRun } from "../lib/api-config-fork";
import { createApiPipelineConfig, initialModelTeams } from "../lib/api-model-teams";
import { parseApiPipelineConfig, type ApiPipelineConfigV2 } from "../lib/api-pipeline-config";
import { addResponsePrompt, loadApiPipelineConfig, saveApiPipelineConfig } from "../lib/api-pipeline-store";
import { pipelineRequest } from "../lib/pipeline-inspection";
import { inspectRecovery, newRecoveryRun } from "../lib/pipeline-recovery";
import { pipelinePython } from "../lib/pipeline-runner";
import { localPipelineWorkspace, writePipelineRecord } from "../lib/pipeline-workspace";
import { updateWorkspaceWorker } from "../lib/pipeline-workspace-state";
import { createProject } from "../lib/project-create";
import { eachCase } from "./cases";

type Effort = "low" | "high";
const route = (effort: Effort) => ({ backend: "openrouter", model: "test/solver", kwargs: { reasoning_effort: effort } });

function config(effort: Effort = "low", prompts?: string[]): ApiPipelineConfigV2 {
  return { version: 2, teams: { generation: { models: ["test/writer"], integrator: "" }, rating: { models: [], integrator: "" }, responses: { models: ["test/solver"], integrator: "", modelReasoning: { "test/solver": effort }, ...(prompts ? { prompts } : {}) }, judge: { models: ["test/judge"], integrator: "" } } };
}

function project(prompts: string[], collected: { plain?: boolean; prompted?: string[]; effort?: Effort } = {}): { root: string; folder: string } {
  const root = mkdtempSync(path.join(os.tmpdir(), "response-prompt-config-"));
  createProject(root, "p", "Synthetic fixture", "api");
  const folder = path.join(root, "p");
  saveApiPipelineConfig(root, "p", config("low", prompts.length ? prompts : undefined));
  const effort = collected.effort ?? "low";
  const sets = [...collected.plain ? ["test/solver"] : [], ...(collected.prompted ?? []).map(id => `test/solver+${id}`)];
  writeFileSync(path.join(folder, "provenance.json"), JSON.stringify({ models: sets, inference: {
    model_routes: Object.fromEntries(sets.map(id => [id, route(effort)])),
    set_prompts: Object.fromEntries((collected.prompted ?? []).map(id => [`test/solver+${id}`, { id, name: id, sha256: "0".repeat(64) }])),
  } }));
  mkdirSync(path.join(folder, "results", "responses"), { recursive: true });
  for (const id of sets) writeFileSync(path.join(folder, "results", "responses", `${id.replace(/[/:]/g, "-")}.jsonl`), JSON.stringify({ id: "Case001", trial: 1, response: "Synthetic", route: route(effort) }) + "\n");
  return { root, folder };
}

test("responses prompts round trip and are validated", () => {
  const original = config("low");
  const text = JSON.stringify(original);
  assert.equal(JSON.stringify(parseApiPipelineConfig(JSON.parse(text))), text);
  const rebuilt = createApiPipelineConfig(initialModelTeams(original));
  assert.equal(JSON.stringify(rebuilt), text);
  assert.equal(JSON.stringify(createApiPipelineConfig({ ...initialModelTeams(original), responses: { ...initialModelTeams(original).responses, prompts: [] } })), text);
  const withPrompts = config("low", ["zeta", "alpha"]);
  assert.deepEqual(parseApiPipelineConfig(withPrompts).teams.responses.prompts, ["zeta", "alpha"]);
  assert.deepEqual(createApiPipelineConfig(initialModelTeams(withPrompts)).teams.responses.prompts, ["zeta", "alpha"]);
  assert.throws(() => parseApiPipelineConfig(config("low", ["Bad Id"])), /prompt/i);
  assert.throws(() => parseApiPipelineConfig(config("low", ["a", "a"])), /duplicate/i);
  const other = config("low"); (other.teams.judge as unknown as Record<string, unknown>).prompts = ["a"];
  assert.equal(parseApiPipelineConfig(other).teams.judge.prompts, undefined);
});

test("the pipeline request carries the prompt for a responses action", () => {
  const { root, folder } = project([]);
  const workspace = { root, project: "p", directory: folder };
  const withPrompt = pipelineRequest(workspace, { stage: "responses", prompt: "safe-first" }, config("low", ["safe-first"])) as { action: Record<string, unknown> };
  assert.deepEqual(withPrompt.action, { stage: "responses", prompt: "safe-first" });
  const without = pipelineRequest(workspace, { stage: "responses" }, config("low")) as { action: Record<string, unknown> };
  assert.deepEqual(without.action, { stage: "responses" });
  const replacing = pipelineRequest(workspace, { stage: "responses", replaceOutdated: true }, config("low")) as { action: Record<string, unknown> };
  assert.deepEqual(replacing.action, { stage: "responses", replaceOutdated: true });
});

const withSecondModel = (): ApiPipelineConfigV2 => { const added = config("low", ["safe"]); added.teams.responses.models.push("test/second"); return added; };
const IMPACT_CASES: { label: string; prompts: string[]; collected: Parameters<typeof project>[1]; next: () => ApiPipelineConfigV2; previous: () => ApiPipelineConfigV2; reason: RegExp | null }[] = [
  { label: "prompt-first project, unchanged", prompts: ["safe"], collected: { prompted: ["safe"] }, next: () => config("low", ["safe"]), previous: () => config("low", ["safe"]), reason: null },
  { label: "plain and prompted sets, unchanged", prompts: ["safe"], collected: { plain: true, prompted: ["safe"] }, next: () => config("low", ["safe"]), previous: () => config("low", ["safe"]), reason: null },
  { label: "adding a prompt", prompts: ["safe"], collected: { plain: true, prompted: ["safe"] }, next: () => config("low", ["safe", "other"]), previous: () => config("low", ["safe"]), reason: null },
  { label: "removing a prompt with collected responses", prompts: ["safe"], collected: { plain: true, prompted: ["safe"] }, next: () => config("low"), previous: () => config("low", ["safe"]), reason: /exclude retained/ },
  { label: "first prompt on a plain-only project", prompts: [], collected: { plain: true }, next: () => config("low", ["fresh"]), previous: () => config("low"), reason: null },
  { label: "reasoning change on prompted-only sets", prompts: ["safe"], collected: { prompted: ["safe"] }, next: () => config("high", ["safe"]), previous: () => config("low", ["safe"]), reason: /reasoning/ },
  { label: "extra model under test", prompts: ["safe"], collected: { prompted: ["safe"] }, next: withSecondModel, previous: () => config("low", ["safe"]), reason: /models under test/ },
];

test("impact of prompt changes", () => eachCase(IMPACT_CASES, (c) => c.label, (c) => {
  const { root } = project(c.prompts, c.collected);
  const impact = apiConfigImpact(root, "p", c.next(), c.previous());
  if (c.reason) assert.match(impact!.reasons.join(" "), c.reason);
  else assert.equal(impact, null);
}));

test("saved routes on prompted sets govern saves", () => {
  const { root, folder } = project(["safe"], { prompted: ["safe"] });
  assert.throws(() => saveApiPipelineConfig(root, "p", config("high", ["safe"])), /new run/i);
  const provenance = JSON.parse(readFileSync(path.join(folder, "provenance.json"), "utf8"));
  provenance.inference.model_routes["test/solver+safe"].model = "test/other";
  writeFileSync(path.join(folder, "provenance.json"), JSON.stringify(provenance));
  assert.match(apiConfigImpact(root, "p", config("low", ["safe"]), config("low", ["safe"]))!.reasons.join(" "), /saved collection route/);
});

test("run support: an unsaved prompt is refused and a saved one is appended to the saved config in order", async () => {
  const { root } = project(["alpha"]);
  const added = addResponsePrompt(root, "p", loadApiPipelineConfig(root, "p")!, "beta");
  assert.deepEqual((added as ApiPipelineConfigV2).teams.responses.prompts, ["alpha", "beta"]);
  assert.deepEqual((loadApiPipelineConfig(root, "p") as ApiPipelineConfigV2).teams.responses.prompts, ["alpha", "beta"]);
  assert.equal(addResponsePrompt(root, "p", added, "alpha"), added);
  const prior = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = root;
  try {
    const response = await runApi(new NextRequest("http://localhost/api/pipeline/run", { method: "POST", headers: { origin: "http://localhost", "Content-Type": "application/json" }, body: JSON.stringify({ project: "p", action: { stage: "responses", prompt: "missing" } }) }));
    assert.equal(response.status, 400);
    assert.match((await response.json() as { error: string }).error, /missing/);
    assert.deepEqual((loadApiPipelineConfig(root, "p") as ApiPipelineConfigV2).teams.responses.prompts, ["alpha", "beta"]);
  } finally { if (prior === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = prior; }
});

test("a fork and a recovered run both copy prompts.json byte for byte", async () => {
  const { root, folder } = project([]);
  const prompts = `${JSON.stringify({ version: 1, prompts: [{ id: "safe", name: "Safe", text: "Think carefully.", sha256: "a".repeat(64), savedAt: "2026-01-01T00:00:00.000Z" }] }, null, 2)}\n`;
  writeFileSync(path.join(folder, "prompts.json"), prompts);
  forkApiRun(root, "p", "forked", config("low"));
  assert.equal(readFileSync(path.join(root, "forked", "prompts.json"), "utf8"), prompts);

  const workspace = localPipelineWorkspace(root, "p");
  const record = { jobId: "12345678-1234-1234-1234-123456789abc", action: { stage: "responses" as const }, config: config("low"), status: "interrupted" as const, startedAt: new Date().toISOString(), finishedAt: new Date().toISOString(), message: "Interrupted", executionDirectory: workspace.directory, operationIdentity: "operation-one" };
  updateWorkspaceWorker(workspace.directory, "p", workspace.key, record.jobId, { state: "exited" });
  writePipelineRecord(workspace.directory, "latest.json", record);
  writePipelineRecord(workspace.directory, `${record.jobId}.json`, record);
  await workspace.publish();
  const reviewed = await inspectRecovery(folder, workspace.key, config("low"), pipelinePython(), async () => ({ status: "blocked", reusableCalls: 0, reason: "Changed rules" }));
  assert.equal(reviewed.plan.status, "new-run");
  newRecoveryRun(root, "p", "recovered", reviewed, { jobId: record.jobId, token: reviewed.plan.token! }, config("low"));
  assert.equal(filesIn(path.join(root, "recovered"))["prompts.json"], filesIn(folder)["prompts.json"]);
  assert.equal(readFileSync(path.join(root, "recovered", "prompts.json"), "utf8"), prompts);
});

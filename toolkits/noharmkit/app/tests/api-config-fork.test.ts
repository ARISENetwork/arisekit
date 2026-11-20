import { createHash } from "node:crypto";
import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { POST as saveConfig } from "../app/api/pipeline/config/route";
import { POST as createRun } from "../app/api/pipeline/config/fork/route";
import { apiConfigImpact, ApiConfigImpactError } from "../lib/api-config-impact";
import { forkApiRun } from "../lib/api-config-fork";
import type { ApiPipelineConfigV2 } from "../lib/api-pipeline-config";
import { loadApiPipelineConfig, saveApiPipelineConfig } from "../lib/api-pipeline-store";
import { createProject } from "../lib/project-create";
import { eachCase } from "./cases";

function config(effort: "low" | "high" = "low"): ApiPipelineConfigV2 {
  return { version: 2, teams: { generation: { models: ["test/writer"], integrator: "" }, rating: { models: [], integrator: "" }, responses: { models: ["test/solver"], integrator: "", modelReasoning: { "test/solver": effort } }, judge: { models: ["test/judge"], integrator: "" } } };
}
function inventory(folder: string, relative = ""): Record<string, string> {
  return Object.fromEntries(readdirSync(path.join(folder, relative), { withFileTypes: true }).flatMap(entry => {
    const name = relative ? `${relative}/${entry.name}` : entry.name;
    return entry.isDirectory() ? Object.entries(inventory(folder, name)) : [[name, createHash("sha256").update(readFileSync(path.join(folder, name))).digest("hex")]];
  }));
}
function fixture(): { root: string; folder: string } {
  const root = mkdtempSync(path.join(os.tmpdir(), "api-config-fork-"));
  createProject(root, "original", "Synthetic fixture");
  const folder = path.join(root, "original");
  saveApiPipelineConfig(root, "original", config());
  mkdirSync(path.join(folder, "results", "responses"), { recursive: true });
  writeFileSync(path.join(folder, "results", "responses", "test-solver.jsonl"), JSON.stringify({ id: "Case001", trial: 1, response: "Synthetic response", route: { backend: "openrouter", model: "test/solver", kwargs: { reasoning_effort: "low" } } }) + "\n");
  return { root, folder };
}

test("settings changes are rejected before overwriting retained configuration or receipts", () => {
  const { root, folder } = fixture();
  const original = readFileSync(path.join(folder, "api-pipeline.json"), "utf8");
  const receipt = readFileSync(path.join(folder, "results/responses/test-solver.jsonl"), "utf8");
  assert.equal(apiConfigImpact(root, "original", config(), config()), null);
  assert.throws(() => saveApiPipelineConfig(root, "original", config("high")), ApiConfigImpactError);
  const added = config(); added.teams.responses.models.push("test/second");
  assert.match(apiConfigImpact(root, "original", added, config())!.reasons.join(" "), /models under test/);
  const removed = config(); removed.teams.responses = { models: ["test/second"], integrator: "" };
  assert.match(apiConfigImpact(root, "original", removed, config())!.reasons.join(" "), /exclude retained/);
  assert.equal(readFileSync(path.join(folder, "api-pipeline.json"), "utf8"), original);
  assert.equal(readFileSync(path.join(folder, "results/responses/test-solver.jsonl"), "utf8"), receipt);
});

test("collection receipt route governs conflicts even if the saved config already drifted", () => {
  const { root, folder } = fixture();
  writeFileSync(path.join(folder, "api-pipeline.json"), JSON.stringify(config("high")));
  assert.match(apiConfigImpact(root, "original", config("high"), config("high"))!.reasons.join(" "), /saved collection route/);
  writeFileSync(path.join(folder, "results/responses/test-solver.jsonl"), JSON.stringify({ error: "timeout", route: { backend: "codex", model: "test/solver", kwargs: {} } }));
  assert.throws(() => saveApiPipelineConfig(root, "original", config()), ApiConfigImpactError);
  writeFileSync(path.join(folder, "results/responses/test-solver.jsonl"), JSON.stringify({ response: "Legacy response" }));
  assert.match(apiConfigImpact(root, "original", config(), config())!.reasons.join(" "), /older collection records/);
});

test("authoring and judge settings remain editable, and response order alone is unchanged scope", () => {
  const { root } = fixture();
  const changed = config(); changed.teams.judge.models = ["test/new-judge"];
  changed.teams.generation.models = ["test/new-writer"];
  assert.deepEqual(saveApiPipelineConfig(root, "original", changed), changed);
  const ordered = config(); ordered.teams.responses.models.push("test/second");
  writeFileSync(path.join(root, "original", "api-pipeline.json"), JSON.stringify(ordered));
  const reordered = structuredClone(ordered); reordered.teams.responses.models.reverse();
  assert.deepEqual(saveApiPipelineConfig(root, "original", reordered), reordered);
  createProject(root, "empty", "");
  assert.deepEqual(saveApiPipelineConfig(root, "empty", config("high")), config("high"));
});

const FORK_CASES: { label: string; provenance: Record<string, unknown>; remove: string[]; files: Record<string, string | Buffer>; copied: string[]; absent: string[]; pin: string | undefined; dropped: string[]; refusals: boolean }[] = [
  {
    label: "pinned source with recorded inference",
    provenance: { judge_scoring_source_commit: "source-runtime-pin", inference: { model_routes: { "test/solver": { backend: "openrouter", model: "test/solver", kwargs: { reasoning_effort: "low" } } } }, models: ["test/solver"] },
    remove: [],
    files: { "cases/Case001.json": '{"presentation":"Original wording"}', "answer-tables/Case001.reviewed-dwu.json": '{"reviewer":"dwu","savedAt":"2026-01-01"}', "imports/source.csv": "original,input\n", "drafts/dataset.json": '{"revision":1,"drafts":{}}', "results/judge/test-solver.jsonl": "{}", "web-execution/latest.json": '{"status":"failed"}' },
    copied: ["items.jsonl", "cases/Case001.json", "answer-tables/Case001.reviewed-dwu.json", "imports/source.csv", "drafts/dataset.json"],
    absent: ["results", "web-execution"],
    pin: "source-runtime-pin",
    dropped: ["inference", "models", "clinicianReviewed"],
    refusals: true,
  },
  {
    label: "unpinned source with model labels and binary input",
    provenance: { model_labels: { "test/solver": "Old solver" } },
    remove: ["judge_scoring_source_commit"],
    files: { "imports/source.bin": Buffer.from([0, 255, 128, 13, 10]), "drafts/dataset.json": '{"drafts":{}}\n', "drafts/other.json": "not selected", "dataset-drafts/legacy.json": "recovery-only input path" },
    copied: ["imports/source.bin", "drafts/dataset.json"],
    absent: ["drafts/other.json", "dataset-drafts"],
    pin: undefined,
    dropped: ["model_labels"],
    refusals: false,
  },
];

test("forks copy exact inputs and the source pin, never results or review", () => eachCase(FORK_CASES, (c) => c.label, (c) => {
  const { root, folder } = fixture();
  const provenanceFile = path.join(folder, "provenance.json");
  const provenance = JSON.parse(readFileSync(provenanceFile, "utf8"));
  for (const key of c.remove) delete provenance[key];
  writeFileSync(provenanceFile, JSON.stringify({ ...provenance, ...c.provenance }));
  for (const [name, body] of Object.entries(c.files)) {
    mkdirSync(path.dirname(path.join(folder, name)), { recursive: true }); writeFileSync(path.join(folder, name), body);
  }
  const original = readFileSync(provenanceFile, "utf8");
  const beforeHashes = inventory(folder);
  forkApiRun(root, "original", "fresh", config("high"));
  assert.deepEqual(inventory(folder), beforeHashes);
  const target = path.join(root, "fresh");
  for (const name of c.copied) assert.deepEqual(readFileSync(path.join(target, name)), readFileSync(path.join(folder, name)), name);
  for (const name of c.absent) assert.equal(existsSync(path.join(target, name)), false, name);
  assert.deepEqual(loadApiPipelineConfig(root, "fresh"), config("high"));
  const copied = JSON.parse(readFileSync(path.join(target, "provenance.json"), "utf8"));
  assert.equal(copied.judge_scoring_source_commit, c.pin);
  for (const key of c.dropped) assert.equal(copied[key], undefined, key);
  assert.equal(copied.forked_from.project, "original");
  assert.equal(readFileSync(provenanceFile, "utf8"), original);
  assert.deepEqual(loadApiPipelineConfig(root, "original"), config());
  if (c.refusals) {
    assert.throws(() => forkApiRun(root, "original", "fresh", config()), /EEXIST/);
    assert.throws(() => forkApiRun(root, "original", "../bad", config()), /Project name/);
  }
}));

test("fork link and exclusion policy", () => {
  const { root, folder } = fixture();
  const excludedDirectories = ["imports/nested-holdout-data", "imports/.hidden", "imports/cache", "imports/secrets"];
  for (const relative of excludedDirectories) {
    mkdirSync(path.join(folder, relative), { recursive: true });
    symlinkSync(path.join(folder, "provenance.json"), path.join(folder, relative, "must-not-inspect.json"));
  }
  for (const relative of ["imports/.env", "imports/api-key.json"]) symlinkSync(path.join(folder, "provenance.json"), path.join(folder, relative));
  writeFileSync(path.join(folder, "imports", "source.csv"), "Task,Solution\n");
  forkApiRun(root, "original", "fresh", config("high"));
  assert.deepEqual(readdirSync(path.join(root, "fresh", "imports")), ["source.csv"]);
  assert.throws(() => forkApiRun(root, "original", "holdout-copy", config()), /cannot be copied/);
  assert.equal(readFileSync(path.join(root, "fresh", "imports", "source.csv"), "utf8"), "Task,Solution\n");
  symlinkSync(path.join(folder, "provenance.json"), path.join(folder, "cases", "Case001.json"));
  assert.throws(() => forkApiRun(root, "original", "linked", config()), /Linked source/);
  assert.equal(existsSync(path.join(root, "linked")), false);
});

test("API conflicts are typed and new-run route selects only the new project, with same-origin protection", async () => {
  const { root, folder } = fixture();
  const priorRoot = process.env.NOHARM_PROJECTS;
  const priorFetch = globalThis.fetch;
  process.env.NOHARM_PROJECTS = root;
  let catalogs = 0;
  globalThis.fetch = (async url => { assert.equal(String(url), "https://openrouter.ai/api/v1/models"); catalogs += 1; return Response.json({ data: ["test/writer", "test/solver", "test/judge"].map(id => ({ id, name: id, context_length: 1000, architecture: { output_modalities: ["text"] }, reasoning: { supported_efforts: ["low", "high"], mandatory: false } })) }); }) as typeof fetch;
  const request = (fork: boolean, origin = "http://localhost"): NextRequest => new NextRequest(`http://localhost/api/pipeline/config${fork ? "/fork" : ""}`, { method: "POST", headers: { origin, "Content-Type": "application/json" }, body: JSON.stringify({ project: "original", name: "fresh", config: config("high") }) });
  try {
    assert.equal((await createRun(request(true, "https://foreign.example"))).status, 403);
    assert.equal(catalogs, 0);
    const conflict = await saveConfig(request(false));
    assert.equal(conflict.status, 409); assert.equal((await conflict.json()).impact.code, "new_run_required");
    assert.deepEqual(loadApiPipelineConfig(root, "original"), config());
    const result = await createRun(request(true));
    assert.equal(result.status, 201); assert.equal(result.cookies.get("noharm-benchmark")!.value, "fresh");
    assert.deepEqual(await result.json(), { project: "fresh", href: "/noharm/dataset" });
    assert.equal((await createRun(request(true))).status, 409);
    assert.equal(existsSync(path.join(folder, "results/responses/test-solver.jsonl")), true);
    assert.deepEqual(readdirSync(root).sort(), ["fresh", "original"]);
  } finally { globalThis.fetch = priorFetch; if (priorRoot === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = priorRoot; }
});

test("an earlier-format setup with saved judgments cannot switch formats, so judging never fails after paid collection", () => {
  const { root, folder } = fixture();
  const earlier = { version: 1 as const, generationModel: "test/writer", ratingModels: [], responseModels: ["test/solver"], judgeModel: "test/judge" };
  assert.doesNotMatch(apiConfigImpact(root, "original", config(), earlier)?.reasons.join(" ") ?? "", /earlier model setup format/);
  mkdirSync(path.join(folder, "results", "judge"), { recursive: true });
  writeFileSync(path.join(folder, "results", "judge", "test-solver.jsonl"), JSON.stringify({ id: "Case001", trial: 1, status: "pass" }) + "\n");
  assert.match(apiConfigImpact(root, "original", config(), earlier)!.reasons.join(" "), /earlier model setup format/);
});

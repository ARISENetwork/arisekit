import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import type { ApiModelTeam } from "../lib/api-model-teams";
import { apiResponseRows } from "../lib/api-response-status";
import { modelLabel, orderResponseSets, promptOf } from "../lib/caseset/model-label";
import { localResponseIndex } from "../lib/caseset/local-responses";
import { listModels } from "../lib/caseset/paths";
import { stepHref } from "../lib/caseset/routes";
import type { Benchmark, CaseStatus, ResponseStatus } from "../lib/caseset/metrics";
import { STEP_KEYS } from "../lib/caseset/steps";
import { modelName, modelOrganization } from "../lib/model-names";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const { textV2LeaderboardRows }: typeof import("../components/mc/TextV2Results") = require("../components/mc/TextV2Results");
const { leaderboardExportRows }: typeof import("../components/mc/steps/LeaderboardStep") = require("../components/mc/steps/LeaderboardStep");
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const SHA = "a".repeat(64);
const EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const route = (model: string) => ({ backend: "openrouter", model, kwargs: {} });

function provenance(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    models: ["test/model-a", "test/model-a+careful", "test/model-b"],
    inference: {
      binding_version: 2,
      model_routes: { "test/model-a": route("test/model-a"), "test/model-a+careful": route("test/model-a"), "test/model-b": route("test/model-b") },
      set_prompts: { "test/model-a+careful": { id: "careful", name: "Careful", sha256: SHA } },
      ...extra,
    },
  };
}

function response(model: string, text = "Synthetic response"): ResponseStatus {
  return {
    caseId: "Case1", autograding: "out of date", clinicianReview: null, scoreBehindReview: false, scoreReviewed: false, limits: [],
    row: { itemId: "Case1", model, trial: 1, response: text, responseError: null, judge: "failed", record: null, judgeCommand: "", scored: null, scoreCheck: null },
  };
}

function benchmark(prov: Record<string, unknown>, responses: ResponseStatus[] = [], models: string[] = []): Benchmark {
  const c: CaseStatus = {
    caseId: "Case1", items: ["Case1"], responses, missing: [], prompts: {}, versionStates: {},
    rubric: { state: "none", versions: [], hasPassing: false, failed: false, mixed: false, disagreements: 0, outOfDate: [], basedOnOlder: [], unusedReviewed: [] },
    page: { caseset: "synthetic", caseId: "Case1", source: { presentation: "Synthetic", recommendations: "Synthetic" }, tables: [], responses: responses.map(r => r.row), provenance: prov, report: null, clinicianReviewed: false, commands: { import: "", generate: "", inference: "", judge: "", score: "" } } as CaseStatus["page"],
  };
  return {
    name: "synthetic", trials: 1, updatedAt: null, models, cases: [c],
    steps: Object.fromEntries(STEP_KEYS.map(key => [key, { key, done: 0, total: 0, reviewed: null, reviewTotal: null, failed: 0, dot: "none" }])) as Benchmark["steps"],
    attention: [], needAttention: 0, awaiting: { rubrics: 0, autograding: 0 }, meanF1: { value: null, n: 0, draft: true, provisional: true }, byModel: [],
  };
}

const luna = {
  models: ["openai/gpt-6-luna", "openai/gpt-6-luna+careful-clinician"],
  inference: { set_prompts: { "openai/gpt-6-luna+careful-clinician": { id: "careful-clinician", name: "Careful clinician", sha256: "a".repeat(64) } } },
};
const LABEL_CASES: { name: string; set: string; provenance: Record<string, unknown>; prompt?: ReturnType<typeof promptOf>; label?: string }[] = [
  { name: "prompted set", set: "test-model-a+careful", provenance: provenance(), prompt: { name: "Careful", sha256: SHA }, label: "model-a, Careful" },
  { name: "unprompted set", set: "test-model-a", provenance: provenance(), prompt: null, label: "model-a" },
  { name: "plus sign without set_prompts", set: "test-model-x", provenance: { models: ["test/model+x"], inference: { model_routes: { "test/model+x": route("test/model+x") } } }, prompt: null },
  { name: "legacy unprompted set", set: "test-model-b", provenance: provenance({ template_sha256: SHA }), prompt: "prompt file", label: "model-b, prompt file" },
  { name: "legacy prompted set", set: "test-model-a+careful", provenance: provenance({ template_sha256: SHA }), prompt: { name: "Careful", sha256: SHA } },
  { name: "empty legacy template", set: "test-model-b", provenance: provenance({ template_sha256: EMPTY_SHA }), prompt: null },
  { name: "current unprompted set", set: "test-model-b", provenance: provenance(), prompt: null },
  { name: "no inference record", set: "test-model-b", provenance: { models: ["test/model-b"] }, label: "model-b" },
  { name: "known model name", set: "openai-gpt-6-luna", provenance: luna, label: "GPT-6 Luna" },
  { name: "known model name with a prompt", set: "openai-gpt-6-luna+careful-clinician", provenance: luna, label: "GPT-6 Luna, Careful clinician" },
  { name: "unlisted vendor model", set: "vendor/unlisted-model", provenance: {}, label: "unlisted-model" },
];

test("response set prompt and label", () => eachCase(LABEL_CASES, (c) => c.name, (c) => {
  if ("prompt" in c) assert.deepEqual(promptOf(c.set, c.provenance), c.prompt);
  if (c.label !== undefined) assert.equal(modelLabel(c.set, c.provenance), c.label);
}));

const team: ApiModelTeam = { models: ["test/model-a", "test/model-b"], integrator: "", prompts: ["careful", "brief"] };

test("apiResponseRows gives one row per response set, unprompted first", () => {
  const rows = apiResponseRows(benchmark(provenance()), team, [{ id: "careful", name: "Careful" }, { id: "brief", name: "Brief" }]);
  assert.deepEqual(rows.map(r => [r.id, r.model, r.prompt]), [
    ["test/model-a", "test-model-a", undefined],
    ["test/model-a+careful", "test-model-a+careful", "Careful"],
    ["test/model-a+brief", "test-model-a+brief", "Brief"],
    ["test/model-b", "test-model-b", undefined],
    ["test/model-b+careful", "test-model-b+careful", "Careful"],
    ["test/model-b+brief", "test-model-b+brief", "Brief"],
  ]);
  assert.equal(Object.hasOwn(rows[0], "prompt"), false);
});

test("apiResponseRows counts each set from its own response file and keeps unprompted rows unchanged", () => {
  const bench = benchmark(provenance(), [response("test-model-a"), response("test-model-a+careful")]);
  const rows = apiResponseRows(bench, team, [{ id: "careful", name: "Careful" }]);
  assert.deepEqual(rows.slice(0, 2).map(r => [r.status, r.completed]), [["Complete", 1], ["Complete", 1]]);
  assert.equal(rows[2].status, "Pending");
  const plain = apiResponseRows(bench, { models: team.models, integrator: "" });
  assert.deepEqual(plain.map(r => r.id), ["test/model-a", "test/model-b"]);
});

test("leaderboard and CSV rows group prompted sets after the unprompted set", () => {
  const prov = provenance();
  const models = ["test-model-b", "test-model-a+careful", "test-model-a"];
  assert.deepEqual(orderResponseSets(models, prov), ["test-model-b", "test-model-a", "test-model-a+careful"]);
  const rows = textV2LeaderboardRows(benchmark(prov, [], models));
  assert.deepEqual(rows.map(r => r.model), ["test-model-b", "test-model-a", "test-model-a+careful"]);
  assert.deepEqual(rows.map(r => r.prompt), [null, null, "Careful"]);
  const exported = leaderboardExportRows(rows);
  assert.deepEqual(Object.keys(exported[0]).slice(0, 3), ["model", "prompt", "prompt_sha256"]);
  assert.deepEqual(exported.map(r => [r.prompt, r.prompt_sha256]), [["", ""], ["", ""], ["Careful", SHA]]);
});

test("known models show their name and organization, from either ID form", () => {
  assert.equal(modelName("openai/gpt-6-luna"), "GPT-6 Luna");
  assert.equal(modelName("google-gemini-3.8-flash"), "Gemini 3.8 Flash");
  assert.equal(modelOrganization("openai/gpt-6-luna"), "OpenAI");
  assert.equal(modelOrganization("qwen/qwen3.8-max-0902"), "Qwen");
  assert.equal(modelName("openrouter-test-model-a"), null);
  assert.equal(modelOrganization("openrouter-test-model-a"), null);
});

test("listModels keeps prompted response set stems", () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "prompted-sets-"));
  mkdirSync(path.join(dir, "results", "responses"), { recursive: true });
  for (const stem of ["demo-lab-model-a", "demo-lab-model-a+careful-triage"]) writeFileSync(path.join(dir, "results", "responses", `${stem}.jsonl`), "");
  assert.deepEqual(listModels(dir), ["demo-lab-model-a", "demo-lab-model-a+careful-triage"]);
});

test("a link to a prompted set round-trips its name", () => {
  const set = "demo-lab-model-a+careful-triage";
  const href = stepHref("responses", { case: "Sample001", item: "Sample001", model: set, trial: 2 });
  assert.match(href, /model=demo-lab-model-a%2Bcareful-triage/);
  const query = new URL(href, "http://local").searchParams;
  assert.equal(query.get("model"), set);
  const views = [{ model: "demo-lab-model-a", trial: 2 }, { model: set, trial: 2 }];
  assert.equal(localResponseIndex(views, { caseId: "Sample001", itemId: "Sample001", model: views[0].model, trial: 2 } as never, query), 1);
});

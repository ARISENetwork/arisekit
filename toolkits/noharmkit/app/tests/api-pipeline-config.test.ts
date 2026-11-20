import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { emptyApiPipelineConfig, parseApiPipelineConfig, type ApiModelOption, type ApiPipelineConfigV1, type ApiPipelineConfigV2 } from "../lib/api-pipeline-config";
import { createApiPipelineConfig, initialModelTeams } from "../lib/api-model-teams";
import { loadApiPipelineConfig, saveApiPipelineConfig, validateApiModels } from "../lib/api-pipeline-store";
import { createProject } from "../lib/project-create";
import { eachCase } from "./cases";

const legacy: ApiPipelineConfigV1 = { version: 1, generationModel: "fixture/writer", ratingModels: ["fixture/rater", "fixture/rater-two"], responseModels: ["fixture/response", "fixture/response-two"], judgeModel: "fixture/judge" };

function teamConfig(): ApiPipelineConfigV2 {
  return { version: 2, teams: {
    generation: { models: ["fixture/writer", "fixture/writer-two"], integrator: "fixture/writer", modelReasoning: { "fixture/writer": "low" }, integratorReasoning: { "fixture/writer": "high" } },
    rating: { models: ["fixture/rater", "fixture/rater-two"], integrator: "fixture/rating-integrator", modelReasoning: { "fixture/rater": "minimal" }, integratorReasoning: { "fixture/rating-integrator": "medium" } },
    responses: { models: ["fixture/response", "fixture/response-two"], integrator: "", modelReasoning: { "fixture/response": "none" } },
    judge: { models: ["fixture/writer", "fixture/judge"], integrator: "fixture/judge-integrator", modelReasoning: { "fixture/writer": "medium" }, integratorReasoning: { "fixture/judge-integrator": "max" } },
  } };
}

function catalog(config: ApiPipelineConfigV2): ApiModelOption[] {
  const ids = [...new Set(Object.values(config.teams).flatMap(team => [...team.models, ...(team.integrator ? [team.integrator] : [])]))];
  return ids.map(id => ({ id, name: id, contextLength: 1000, inputPrice: null, outputPrice: null, structured: true, reasoning: { efforts: ["none", "minimal", "low", "medium", "high", "max"], mandatory: false } }));
}

test("version 1 configuration remains unchanged and no integrator or reasoning is inferred", () => {
  const before = structuredClone(legacy);
  assert.deepEqual(parseApiPipelineConfig(legacy), legacy);
  const teams = initialModelTeams(legacy);
  assert.deepEqual(teams.generation, { models: [legacy.generationModel], integrator: "" });
  assert.deepEqual(teams.rating, { models: legacy.ratingModels, integrator: "" });
  assert.deepEqual(teams.responses, { models: legacy.responseModels, integrator: "" });
  assert.deepEqual(teams.judge, { models: [legacy.judgeModel], integrator: "" });
  const models = [...new Set([legacy.generationModel, ...legacy.ratingModels, ...legacy.responseModels, legacy.judgeModel])].map(id => ({ id, name: id, contextLength: 0, inputPrice: null, outputPrice: null, structured: false }));
  validateApiModels(legacy, models);
  teams.rating.models.pop();
  assert.deepEqual(legacy, before);
  assert.equal(emptyApiPipelineConfig().version, 1);
});

test("version 2 round trips independent stage, contributor, and integrator reasoning", () => {
  const config = teamConfig();
  const before = structuredClone(config);
  assert.deepEqual(parseApiPipelineConfig(config), config);
  const teams = initialModelTeams(config);
  assert.deepEqual(createApiPipelineConfig(teams), config);
  assert.equal(teams.generation.modelReasoning?.["fixture/writer"], "low");
  assert.equal(teams.generation.integratorReasoning?.["fixture/writer"], "high");
  assert.equal(teams.judge.modelReasoning?.["fixture/writer"], "medium");
  teams.generation.models.pop();
  teams.generation.modelReasoning!["fixture/writer"] = "minimal";
  teams.generation.integratorReasoning!["fixture/writer"] = "medium";
  assert.deepEqual(config, before);
});

test("UI serialization trims inactive cached selections without modifying editor state", () => {
  const teams = initialModelTeams(teamConfig());
  teams.generation.models = ["fixture/writer"];
  teams.generation.integrator = "cached/old-integrator";
  teams.generation.modelReasoning!["cached/removed"] = "high";
  teams.generation.integratorReasoning!["cached/old-integrator"] = "max";
  teams.rating = { models: [], integrator: "cached/rating-integrator", modelReasoning: { "cached/rater": "low" }, integratorReasoning: { "cached/rating-integrator": "high" } };
  teams.responses.integratorReasoning = { "fixture/response-integrator": "low", "cached/old-integrator": "medium" };
  const before = structuredClone(teams);
  const saved = createApiPipelineConfig(teams);
  assert.deepEqual(saved.teams.generation, { models: ["fixture/writer"], integrator: "", modelReasoning: { "fixture/writer": "low" } });
  assert.deepEqual(saved.teams.rating, { models: [], integrator: "" });
  assert.equal(saved.teams.responses.integratorReasoning, undefined);
  assert.equal(saved.teams.responses.integrator, "");
  assert.deepEqual(teams, before);
});

test("parsing drops inactive and response integrators without inventing reasoning", () => {
  const raw = teamConfig();
  raw.teams.generation = { models: ["fixture/writer"], integrator: "subscription/unused", integratorReasoning: { "subscription/unused": "high" } };
  raw.teams.rating = { models: [], integrator: "cached/unused" };
  raw.teams.responses.integrator = "unavailable/legacy-integrator";
  raw.teams.responses.integratorReasoning = { "unavailable/legacy-integrator": "invalid" as never };
  const before = structuredClone(raw);
  const parsed = parseApiPipelineConfig(raw);
  assert.deepEqual(parsed.teams.generation, { models: ["fixture/writer"], integrator: "" });
  assert.deepEqual(parsed.teams.rating, { models: [], integrator: "" });
  assert.equal(parsed.teams.responses.integratorReasoning, undefined);
  const expected = { models: raw.teams.responses.models, integrator: "", modelReasoning: raw.teams.responses.modelReasoning };
  assert.deepEqual(parsed.teams.responses, expected);
  assert.deepEqual(initialModelTeams(raw).responses, expected);
  assert.deepEqual(createApiPipelineConfig(initialModelTeams(raw)).teams.responses, expected);
  validateApiModels(raw, catalog(teamConfig()), "responses");
  assert.deepEqual(raw, before);
});

test("strict parsing rejects invalid active models, duplicates, integrators, and reasoning", () => {
  const mutate = (change: (config: ApiPipelineConfigV2) => void): ApiPipelineConfigV2 => { const config = teamConfig(); change(config); return config; };
  const invalid: unknown[] = [
    { version: 3 }, { version: 2, teams: {} },
    ...(["generation", "responses", "judge"] as const).map(stage => mutate(config => { config.teams[stage].models = []; })),
    mutate(config => { config.teams.rating.models = ["fixture/rater", "fixture/rater"]; }),
    mutate(config => { config.teams.generation.models[0] = "codex/subscription"; }),
    mutate(config => { config.teams.generation.integrator = ""; }),
    mutate(config => { config.teams.judge.integrator = "direct/model"; }),
    mutate(config => { config.teams.generation.modelReasoning = { "fixture/writer": "invented" as never }; }),
    mutate(config => { config.teams.generation.modelReasoning = { "fixture/removed": "low" }; }),
    mutate(config => { config.teams.generation.integratorReasoning = { "fixture/writer-two": "high" }; }),
    mutate(config => { config.teams.rating.integratorReasoning = { "fixture/rating-integrator": "" as never }; }),
    mutate(config => { config.teams.responses.modelReasoning = [] as never; }),
  ];
  invalid.forEach(config => assert.throws(() => parseApiPipelineConfig(config), TypeError));
});

const without = (id: string) => (config: ApiPipelineConfigV2): ApiModelOption[] => catalog(config).filter(model => model.id !== id);
const writerReasoning = (reasoning: ApiModelOption["reasoning"]) => (config: ApiPipelineConfigV2): ApiModelOption[] => catalog(config).map(model => model.id === "fixture/writer" ? { ...model, reasoning } : model);
const noMetadata = (config: ApiPipelineConfigV2): ApiModelOption[] => catalog(config).map(({ reasoning: _reasoning, ...model }) => model);
const noEfforts = (config: ApiPipelineConfigV2): ApiPipelineConfigV2 => {
  for (const team of Object.values(config.teams)) { delete team.modelReasoning; delete team.integratorReasoning; }
  return config;
};
const VALIDATION_CASES: { label: string; config?: (config: ApiPipelineConfigV2) => ApiPipelineConfigV2; models: (config: ApiPipelineConfigV2) => ApiModelOption[]; stage?: Parameters<typeof validateApiModels>[2]; error?: RegExp; check?: (config: ApiPipelineConfigV2) => void }[] = [
  { label: "full catalog for every stage", models: catalog },
  { label: "missing rating integrator", models: without("fixture/rating-integrator"), stage: "generate", error: /fixture\/rating-integrator/ },
  { label: "missing second response model", models: without("fixture/response-two"), stage: "responses", error: /fixture\/response-two/ },
  { label: "missing judge integrator", models: without("fixture/judge-integrator"), stage: "judge", error: /fixture\/judge-integrator/ },
  { label: "judge models absent when collecting responses", models: config => catalog(config).filter(model => !config.teams.judge.models.includes(model.id) && model.id !== config.teams.judge.integrator), stage: "responses" },
  { label: "empty catalog for scoring", models: () => [], stage: "score" },
  { label: "mandatory low/high writer for generation", models: writerReasoning({ efforts: ["low", "high"], mandatory: true }), stage: "generate" },
  { label: "mandatory low/high writer refuses judge medium", models: writerReasoning({ efforts: ["low", "high"], mandatory: true }), stage: "judge", error: /judge contributor fixture\/writer.*medium/ },
  { label: "contributor-only low refuses integrator high", models: writerReasoning({ efforts: ["low"], mandatory: false }), stage: "generate", error: /generation integrator fixture\/writer.*high/ },
  { label: "no reasoning metadata refuses explicit reasoning", models: noMetadata, error: /does not list support/ },
  { label: "no explicit reasoning needs no metadata", config: noEfforts, models: noMetadata, check: config => assert.equal(parseApiPipelineConfig(config).teams.generation.modelReasoning, undefined) },
];

test("validateApiModels", () => eachCase(VALIDATION_CASES, (c) => c.label, (c) => {
  const config = c.config ? c.config(teamConfig()) : teamConfig();
  const models = c.models(config);
  if (c.error) assert.throws(() => validateApiModels(config, models, c.stage), c.error);
  else validateApiModels(config, models, c.stage);
  c.check?.(config);
}));

test("configuration saves round trip both versions, refuse invalid replacements, and protect Local and prepared projects", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "api-config-contract-"));
  createProject(root, "example", "", "api");
  assert.deepEqual(saveApiPipelineConfig(root, "example", legacy), legacy);
  assert.deepEqual(loadApiPipelineConfig(root, "example"), legacy);
  const config = teamConfig();
  assert.deepEqual(saveApiPipelineConfig(root, "example", config), config);
  assert.deepEqual(loadApiPipelineConfig(root, "example"), config);
  const file = path.join(root, "example", "api-pipeline.json");
  const before = readFileSync(file, "utf8");
  const invalid = structuredClone(config); invalid.teams.generation.integrator = "";
  assert.throws(() => saveApiPipelineConfig(root, "example", invalid), TypeError);
  assert.equal(readFileSync(file, "utf8"), before);
  assert.ok(readdirSync(path.dirname(file)).every(name => !name.startsWith(".api-pipeline-")));
  const tutorial = "tutorial-12345678-1234-1234-1234-123456789abc";
  createProject(root, "local-example", "", "local");
  createProject(root, tutorial, "", "api");
  createProject(root, "demo", "", "api");
  const provenanceFile = path.join(root, "demo", "provenance.json");
  writeFileSync(provenanceFile, JSON.stringify({ ...JSON.parse(readFileSync(provenanceFile, "utf8")), synthetic: true }));
  for (const project of ["local-example", tutorial, "demo"]) {
    assert.throws(() => saveApiPipelineConfig(root, project, config), /Local|API Mode|read-only/);
    assert.equal(existsSync(path.join(root, project, "api-pipeline.json")), false);
  }
  writeFileSync(provenanceFile, JSON.stringify({ ...JSON.parse(readFileSync(provenanceFile, "utf8")), synthetic: false }));
  assert.deepEqual(saveApiPipelineConfig(root, "demo", config), config);
});

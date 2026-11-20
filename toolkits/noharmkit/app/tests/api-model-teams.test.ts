import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { initialModelTeams, toggleTeamModel, setTeamReasoning } from "../lib/api-model-teams";
import type { ApiPipelineConfig, ApiModelOption } from "../lib/api-pipeline-config";
import { parseModelReasoning, defaultReasoningLabel, REASONING_EFFORTS } from "../lib/api-model-reasoning";
import { parseOpenRouterModels } from "../lib/openrouter-models";
import { recommendedModels, RECOMMENDED_MODEL_IDS } from "../lib/api-model-shortlist";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = { __esModule: true, default: new Proxy({}, { get: (_target, key) => key }) }; };
const { default: ApiModelSetup, ModelTeamEditor, ReasoningSelect }: typeof import("../components/mc/ApiModelSetup") = require("../components/mc/ApiModelSetup");
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const config: ApiPipelineConfig = { version: 1, generationModel: "retained/writer", ratingModels: ["retained/rater", "retained/rater-two"], responseModels: ["retained/tested"], judgeModel: "retained/judge" };

test("reasoning options follow explicit catalog metadata and omit Off for mandatory reasoning", () => {
  const required = parseModelReasoning({ supported_efforts: ["high", "low", "none", "invented"], mandatory: true, default_effort: "high" })!;
  assert.deepEqual(required.efforts, ["low", "high"]);
  assert.equal(defaultReasoningLabel(required), "Default (High)");
  assert.deepEqual(parseModelReasoning({ supported_efforts: null })?.efforts, [...REASONING_EFFORTS]);
  assert.equal(parseModelReasoning({ supports_max_tokens: true }), undefined);
  assert.equal(parseModelReasoning(undefined), undefined);
  assert.equal(parseModelReasoning({ supported_efforts: [] }), undefined);
  const optional = parseModelReasoning({ supported_efforts: ["none", "high"], default_enabled: false, default_effort: "none" })!;
  assert.equal(defaultReasoningLabel(optional), "Default (Off)");
  const [catalog] = parseOpenRouterModels({ data: [{ id: "fixture/reasoning", name: "Fixture", architecture: { output_modalities: ["text"] }, reasoning: { supported_efforts: ["low", "high"] } }] });
  assert.deepEqual(catalog.reasoning?.efforts, ["low", "high"]);
});

test("team edits keep reasoning and integrators independent", () => {
  const teams = initialModelTeams();
  const model = setTeamReasoning(teams.generation, "modelReasoning", "fixture/one", "low");
  const integrator = setTeamReasoning(model, "integratorReasoning", "fixture/one", "high");
  assert.equal(integrator.modelReasoning?.["fixture/one"], "low");
  assert.equal(integrator.integratorReasoning?.["fixture/one"], "high");
  assert.deepEqual(teams.judge, { models: ["openai/gpt-6.1-sol"], integrator: "", modelReasoning: { "openai/gpt-6.1-sol": "high" } });
  assert.ok([teams.generation, teams.rating, teams.responses].every(team => !team.models.length && !team.integrator));
  assert.equal(teams.generation.modelReasoning, undefined);
  const restored = toggleTeamModel(toggleTeamModel({ ...integrator, models: ["fixture/one"] }, "fixture/one"), "fixture/one");
  assert.deepEqual(restored.modelReasoning, integrator.modelReasoning);
  assert.equal(setTeamReasoning(integrator, "modelReasoning", "fixture/one", "").modelReasoning?.["fixture/one"], undefined);
  assert.equal(integrator.modelReasoning?.["fixture/one"], "low");
  const original = { models: ["fixture/one"], integrator: "fixture/integrator" };
  const multiple = toggleTeamModel(original, "fixture/two");
  assert.deepEqual(multiple.models, ["fixture/one", "fixture/two"]);
  assert.deepEqual(toggleTeamModel(multiple, "fixture/two"), original);
  assert.deepEqual(original.models, ["fixture/one"]);
});

test("reasoning selectors only appear for applicable models and expose exactly their supported levels", () => {
  const model: ApiModelOption = { id: "fixture/one", name: "Fixture", contextLength: 1000, inputPrice: null, outputPrice: null, structured: true };
  const render = (selected: ApiModelOption): string => renderToStaticMarkup(createElement(ReasoningSelect, { model: selected, label: "Reasoning", onChange() {} }));
  assert.equal(render(model), "");
  const html = render({ ...model, reasoning: { efforts: ["low", "high"], mandatory: true, defaultEffort: "high" } });
  assert.match(html, /Default \(High\)/);
  assert.match(html, /value="low"/);
  assert.match(html, /value="high"/);
  assert.doesNotMatch(html, /value="none"|value="medium"|value="max"/);
});

test("the shortlist uses only available catalog models and preserves live names and prices", () => {
  const option = (id: string) => ({ id, name: id, contextLength: 1000, inputPrice: "0.000002", outputPrice: "0.00001", structured: true });
  const first = option(RECOMMENDED_MODEL_IDS[0]);
  const last = option(RECOMMENDED_MODEL_IDS.at(-1)!);
  const catalog = [last, option("fixture/other"), option(`${first.id}:batch`), first];
  const shortlist = recommendedModels(catalog);
  assert.deepEqual(shortlist, [first, last]);
  assert.equal(shortlist[0], first);
  assert.deepEqual(recommendedModels([]), []);
  assert.equal(new Set(RECOMMENDED_MODEL_IDS).size, RECOMMENDED_MODEL_IDS.length);
});

const INTEGRATOR_CASES: { label: string; stage: "generation" | "responses"; title: string; integration: string; models: string[]; integrator: string; match: RegExp[]; absent: RegExp[] }[] = [
  ...[0, 1, 2].map(count => ({
    label: `generation with ${count} contributor${count === 1 ? "" : "s"}`, stage: "generation" as const, title: "Rubric generation", integration: "Combine drafts.",
    models: ["saved/one", "saved/two"].slice(0, count), integrator: "saved/integrator",
    match: [new RegExp(`data-open="${count > 1}"${count > 1 ? "" : ' inert="" aria-hidden="true"'}><div class="disclosureInner"><div class="integrator"`), /saved\/integrator/], absent: [],
  })),
  {
    label: "models under test never expose an integrator", stage: "responses", title: "Models under test", integration: "",
    models: ["saved/one", "saved/two"], integrator: "saved/legacy-integrator",
    match: [/saved\/one/, /saved\/two/], absent: [/responses-integrator|saved\/legacy-integrator|Required for multiple models/],
  },
];

test("integrator disclosure by stage and team size", () => eachCase(INTEGRATOR_CASES, (c) => c.label, (c) => {
  const html = renderToStaticMarkup(createElement(ModelTeamEditor, { stage: c.stage, title: c.title, integration: c.integration, team: { models: c.models, integrator: c.integrator }, models: [], onChange() {} }));
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
}));

test("the active setup offers all four AI stages and saves configuration separately from execution", () => {
  const html = renderToStaticMarkup(createElement(ApiModelSetup, { project: "example", models: [], initialConfig: config }));
  for (const name of ["rubric generation models", "harm rating models", "models under test", "autograding models"]) assert.ok(html.includes(`Select ${name}`));
  assert.match(html, /Deterministic\. No model or integrator needed/);
  assert.match(html, /<form/);
  assert.match(html, /type="submit">Save and continue/);
  assert.match(html, /Saving does not run models/);
  assert.doesNotMatch(html, /Design preview|Current handoff|Copy choices/);
  assert.match(html, /retained\/writer/);
  assert.doesNotMatch(html, /Draft Decisions and Options|proposed harm ratings/);
  const local = renderToStaticMarkup(createElement(ApiModelSetup, { project: "example", models: [], editable: false }));
  assert.match(local, /disabled="">Save and continue/);
});


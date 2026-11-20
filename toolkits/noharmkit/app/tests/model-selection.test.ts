import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { modelSelectionHandoff } from "../lib/model-selection";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const ModelChecklist: typeof import("../components/mc/ModelChecklist").default = require("../components/mc/ModelChecklist").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const custom = "custom/provider-model";
const suggested = "openai/gpt-6-astra";

function render(plannedModels: string[]): string {
  return renderToStaticMarkup(createElement(ModelChecklist, { project: "example", plannedModels }));
}

const CHECKLIST_CASES: { label: string; planned: string[]; match: RegExp[]; absent: RegExp[]; includes: string[]; once: RegExp[] }[] = [
  {
    label: "custom-only project models remain visible, selected, and available for handoff", planned: [custom],
    match: [/Select existing model custom\/provider-model/, /checked=""/, /1 selected/, /Keep these existing models with their current backends and routes/],
    absent: [/disabled=""/, /href="https:\/\/openrouter.ai\/custom\/provider-model"/], includes: [custom], once: [],
  },
  {
    label: "mixed selections keep custom and catalog IDs without duplicate rows", planned: [custom, suggested, custom],
    match: [/2 selected/], absent: [], includes: [custom, suggested],
    once: [/aria-label="Select existing model custom\/provider-model"/g, /aria-label="Select OpenAI GPT-6 Astra"/g],
  },
  { label: "new projects start with an empty selection", planned: [], match: [/Select at least one model/, /disabled=""/], absent: [], includes: [], once: [] },
];

test("model checklist renders planned models", () => eachCase(CHECKLIST_CASES, (c) => c.label, (c) => {
  const html = render(c.planned);
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
  for (const text of c.includes) assert.ok(html.includes(text), text);
  for (const pattern of c.once) assert.equal((html.match(pattern) ?? []).length, 1, String(pattern));
}));

const ADD_HEADER = "Add these selected models through OpenRouter:";
const REMOVE_HEADER = "Remove only these explicitly deselected models from the planned set:\n";
const HANDOFF_CASES: { label: string; project: string; planned: string[]; selected: string[]; retained: string[]; notRetained: string[]; added?: string; removed?: string | RegExp; prompt: RegExp[] }[] = [
  {
    label: "adding a suggestion keeps existing models and routes", project: "example", planned: [custom, "codex:gpt-6-astra"], selected: [custom, "codex:gpt-6-astra", suggested],
    retained: [custom, "codex:gpt-6-astra"], notRetained: [], added: JSON.stringify(suggested), removed: /^None\./,
    prompt: [/Do not remove any other models or change existing routes/, /Preserve stored responses, trials, and run identities/, /Do not collect responses yet/],
  },
  {
    label: "only explicitly deselected IDs are removed", project: "example", planned: [custom, suggested], selected: [suggested],
    retained: [suggested], notRetained: [custom], removed: JSON.stringify(custom), prompt: [],
  },
  { label: "a new project adds the suggested model", project: "new-project", planned: [], selected: [suggested], retained: [], notRetained: [], added: JSON.stringify(suggested), prompt: [] },
];

test("model selection handoff", () => eachCase(HANDOFF_CASES, (c) => c.label, (c) => {
  const before = JSON.stringify(c);
  const prompt = modelSelectionHandoff(c.project, c.planned, c.selected);
  const retained = prompt.split(ADD_HEADER)[0];
  for (const id of c.retained) assert.ok(retained.includes(JSON.stringify(id)), id);
  for (const id of c.notRetained) assert.ok(!retained.includes(JSON.stringify(id)), id);
  if (c.added !== undefined) assert.equal(prompt.split(`${ADD_HEADER}\n`)[1].split("\n\n")[0], c.added);
  const removed = prompt.split(REMOVE_HEADER)[1]?.split("\n\n")[0];
  if (typeof c.removed === "string") assert.equal(removed, c.removed);
  else if (c.removed) assert.match(removed ?? "", c.removed);
  for (const pattern of c.prompt) assert.match(prompt, pattern);
  assert.equal(JSON.stringify(c), before);
}));

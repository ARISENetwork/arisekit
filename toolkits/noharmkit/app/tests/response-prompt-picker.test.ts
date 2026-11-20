import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { loadBenchmark } from "../lib/caseset/metrics";
import { resolveStepParams } from "../lib/caseset/routes";
import { autogradeLabel, collectLabel, outdatedResponses, replaceAutogradingNote, staleAutograding, responsesAction, responsesAgentPrompt, responsesAsk, responsesProposal, runPromptView, plannedModelIds } from "../lib/response-prompt-picker";
import { buildFixture, CASESET } from "./caseset-fixture";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const ResponsesStep: typeof import("../components/mc/steps/ResponsesStep").default = require("../components/mc/steps/ResponsesStep").default;
const { ResponsePromptProvider, default: ResponsePromptPicker }: typeof import("../components/mc/ResponsePromptPicker") = require("../components/mc/ResponsePromptPicker");
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const chosen = { id: "safety-first", name: "Safety first", text: "Answer as a cautious clinician.\nName the main risk." };

test("a chosen prompt reaches the action, proposal, agent command, and inline button, and no prompt adds nothing", () => {
  assert.deepEqual(responsesAction(null), { stage: "responses" });
  assert.deepEqual(responsesAction(chosen), { stage: "responses", prompt: "safety-first" });
  assert.equal(responsesProposal(null), "All imported cases, using the saved model and trial scope.");
  const text = responsesProposal(chosen);
  assert.match(text, /Prompt: Safety first/);
  assert.ok(text.includes(chosen.text));
  const agentBase = "Use noharm-responses for project \"p\". Collect independent responses using the agreed models.";
  assert.equal(responsesAgentPrompt(agentBase, null), agentBase);
  assert.match(responsesAgentPrompt(agentBase, chosen), /--prompt safety-first/);
  const base = "Use noharm-responses.";
  const none = responsesAsk(base, null);
  assert.deepEqual(none.action, { stage: "responses" });
  assert.equal(none.apiLead, undefined);
  assert.equal(none.prompt, base);
  const some = responsesAsk(base, chosen);
  assert.deepEqual(some.action, { stage: "responses", prompt: "safety-first" });
  assert.ok(some.apiLead?.includes("Safety first") && some.apiLead.includes(chosen.text));
  assert.ok(!some.apiLead?.includes("All imported cases"), "the inline action prints its own scope line");
  assert.match(some.prompt, /--prompt safety-first/);
});

test("local mode renders the prompt picker above the models panel", () => {
  const bench = loadBenchmark(buildFixture().root, CASESET);
  const params = resolveStepParams(bench, {})!;
  const html = renderToStaticMarkup(createElement(ResponsePromptProvider, null, ResponsesStep({ bench, params }).props.inputsBelow));
  assert.match(html, /No prompt/);
  assert.match(html, /New prompt\.\.\./);
  assert.ok(html.indexOf("Prompt") < html.indexOf("Models to test"));
});

test("a resumed run resolves its prompt from the saved prompts and the recorded hash", () => {
  const saved = [{ ...chosen, sha256: "aaa" }];
  assert.deepEqual(runPromptView("safety-first", saved, {}), { state: "ok", id: "safety-first", name: "Safety first", text: chosen.text });
  assert.deepEqual(runPromptView("safety-first", saved, { "safety-first": "aaa" }).state, "ok");
  const changed = runPromptView("safety-first", saved, { "safety-first": "bbb" });
  assert.equal(changed.state, "blocked");
  assert.match(changed.state === "blocked" ? changed.reason : "", /differs/);
  const missing = runPromptView("gone", saved, {});
  assert.equal(missing.state, "blocked");
  assert.match(missing.state === "blocked" ? missing.reason : "", /no longer saved/);
});

test("planned models for the agent handoff leave out prompted response sets", () => {
  const provenance = { models: ["m/a", "m/a+careful", 7], inference: { set_prompts: { "m/a+careful": { id: "careful" } } } };
  assert.deepEqual(plannedModelIds(provenance), ["m/a"]);
  assert.deepEqual(plannedModelIds({ models: ["m/a"] }), ["m/a"]);
  assert.deepEqual(plannedModelIds({}), []);
});

const MALFORMED_CASES: { label: string; unavailable?: string; inUse?: boolean; match: RegExp[]; absent: RegExp[] }[] = [
  { label: "a readable file keeps the picker enabled", match: [], absent: [/<select[^>]*disabled/] },
  {
    label: "an error disables the picker and shows the error", unavailable: "Malformed prompts.json: prompts must be a list.",
    match: [/<select[^>]*disabled/, /Malformed prompts\.json: prompts must be a list\./, /without a prompt still works only if no saved prompt is in use/], absent: [],
  },
  { label: "no saved prompt in use", unavailable: "Bad file.", inUse: false, match: [/Bad file\. Collection without a prompt still works\.</], absent: [] },
  {
    label: "a saved prompt in use", unavailable: "Bad file.", inUse: true,
    match: [/Bad file\. Collection without a prompt is blocked too, because this project already uses saved prompts\.</], absent: [/still works/],
  },
];

test("malformed prompts file", () => eachCase(MALFORMED_CASES, (c) => c.label, (c) => {
  const html = renderToStaticMarkup(createElement(ResponsePromptProvider, null, createElement(ResponsePromptPicker, { project: "p", unavailable: c.unavailable, inUse: c.inUse })));
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
}));

test("responses collected for an earlier Task are counted and replaced only on confirmation", () => {
  const cases = [
    { caseId: "Case001", responses: [{ row: { outdated: "task" } }, { row: { outdated: "task" } }, { row: {} }] },
    { caseId: "Case002", responses: [{ row: { outdated: "solution" } }] },
  ];
  const outdated = outdatedResponses(cases);
  assert.deepEqual(outdated, { count: 2, cases: ["Case001"] });
  assert.deepEqual(outdatedResponses([cases[1]]), { count: 0, cases: [] });
  assert.equal(collectLabel(outdated), "Replace and collect");
  assert.equal(collectLabel(outdatedResponses([])), "Collect Responses");
  assert.deepEqual(responsesAction(chosen, outdated), { stage: "responses", prompt: "safety-first", replaceOutdated: true });
  assert.match(responsesProposal(null, outdated), /^All imported cases, using the saved model and trial scope\. 2 responses for Case001 were collected for an earlier Task\. .*results\/superseded\//);
  const ask = responsesAsk("Use noharm-responses.", null, outdated);
  assert.equal(ask.label, "Replace and collect");
  assert.deepEqual(ask.action, { stage: "responses", replaceOutdated: true });
  assert.ok(ask.apiLead && !ask.apiLead.includes("All imported cases"), "the inline action prints its own scope line");
  assert.match(responsesAgentPrompt("Use noharm-responses.", null, outdated), /noharm\.py replace-outdated/);
});

test("autograding made against an out-of-date rubric is counted and replaced only on confirmation", () => {
  const cases = [
    { caseId: "Case001", page: { tables: [{ version: "run1", outdated: "task" }, { version: "run2" }] }, responses: [{ row: { record: { rubric: "run1" } } }, { row: { record: { rubric: "run2" } } }, { row: { record: null } }] },
    { caseId: "Case002", page: { tables: [{ version: "run1" }] }, responses: [{ row: { record: { rubric: "run1" } } }] },
  ];
  const stale = staleAutograding(cases);
  assert.deepEqual(stale, { count: 1, cases: ["Case001"] });
  assert.equal(autogradeLabel(stale), "Replace and autograde");
  assert.equal(autogradeLabel(staleAutograding([cases[1]])), "Run Autograder");
  assert.match(replaceAutogradingNote(stale), /1 autograding result for Case001 used a rubric made before the case text was edited\..*results\/superseded\//);
  assert.equal(replaceAutogradingNote(staleAutograding([])), "");
});

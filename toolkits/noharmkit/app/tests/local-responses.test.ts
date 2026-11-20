import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { LocalResponsesData } from "../components/mc/LocalResponses";

import { isLocalResponseChange, localResponseIndex, navigateLocalResponse } from "../lib/caseset/local-responses";
import { loadBenchmark } from "../lib/caseset/metrics";
import { resolveStepParams, stepHref, type StepParams } from "../lib/caseset/routes";
import { buildFixture, CASESET, MODEL_A, MODEL_B } from "./caseset-fixture";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const ResponsesStep: typeof import("../components/mc/steps/ResponsesStep").default = require("../components/mc/steps/ResponsesStep").default;
const { default: LocalResponses, LocalResponseSlot }: typeof import("../components/mc/LocalResponses") = require("../components/mc/LocalResponses");
const { SearchParamsContext } = require("next/dist/shared/lib/hooks-client-context.shared-runtime");
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const initial: StepParams = { caseId: "Test002", itemId: "Test002", model: "model-a", trial: 2, version: "run1" };
const views = [{ model: "model-a", trial: 1 }, { model: "model-b", trial: 1 }, { model: "model-a", trial: 2 }];
const href = (model: string, trial = 1) => stepHref("responses", { case: initial.caseId, item: initial.itemId, model, trial });

const tutorial = (model: string): string => `/noharm/tutorial?step=responses&case=${initial.caseId}&item=${initial.itemId}&model=${model}&trial=1`;

const CHANGES: Array<{ label: string; from: string | null; to: string; local: boolean }> = [
  { label: "responses root to another model", from: "/noharm/responses", to: href("model-b"), local: true },
  { label: "another model and trial on the same input", from: href("model-a", 2), to: href("model-b"), local: true },
  { label: "no current URL", from: null, to: href("model-b"), local: false },
  { label: "another case", from: href("model-a"), to: "/noharm/responses?case=Test003&item=Test003", local: false },
  { label: "another step", from: href("model-a"), to: "/noharm/autograding?case=Test002", local: false },
  { label: "a model change on another step", from: "/noharm/scores?case=Test002&model=a", to: "/noharm/scores?case=Test002&model=b", local: false },
  { label: "walkthrough responses root to another model", from: "/noharm/tutorial?step=responses", to: tutorial("model-b"), local: true },
  { label: "walkthrough model change", from: tutorial("model-a"), to: tutorial("model-b"), local: true },
  ...["rubrics", "autograding"].map((step) => ({ label: `walkthrough change to the ${step} step`, from: tutorial("model-a"), to: tutorial("model-b").replace("step=responses", `step=${step}`), local: false })),
];

test("only in-place response selections skip the full-page history animation", () => eachCase(CHANGES, (c) => c.label, (c) => {
  assert.equal(isLocalResponseChange(c.from, c.to), c.local);
}));

test("navigateLocalResponse keeps loaded selections local, Back restores each identity, and everything else goes to the server", () => {
  const tutorialCurrent = `http://localhost${tutorial("model-a")}`;
  const tutorialPushed: string[] = [];
  assert.equal(navigateLocalResponse(tutorial("model-b"), tutorialCurrent, initial, views, (next) => tutorialPushed.push(next)), true);
  assert.equal(tutorialPushed.length, 1);
  assert.equal(localResponseIndex(views, initial, new URL(`http://localhost${tutorialPushed[0]}`).searchParams), 1);
  for (const step of ["rubrics", "autograding"]) {
    const target = tutorial("model-b").replace("step=responses", `step=${step}`);
    assert.equal(navigateLocalResponse(target, tutorialCurrent, initial, views, () => assert.fail("Page changes must navigate normally")), false);
  }

  const history = [href("model-a", 2)];
  const pushed: string[] = [];
  for (const model of ["model-b", "model-a"]) {
    assert.equal(navigateLocalResponse(href(model), `http://localhost${history.at(-1)}`, initial, views, (next) => { history.push(next); pushed.push(next); }), true);
  }
  assert.deepEqual(pushed, [href("model-b"), href("model-a")]);
  assert.equal(localResponseIndex(views, initial, new URL(`http://localhost${history.pop()}`).searchParams), 0);
  assert.equal(localResponseIndex(views, initial, new URL(`http://localhost${history.pop()}`).searchParams), 1);
  assert.equal(localResponseIndex(views, initial, new URL(`http://localhost${history.pop()}`).searchParams), 2);
  assert.equal(localResponseIndex(views, initial, new URLSearchParams()), 2);

  const current = `http://localhost${href("model-a", 2)}`;
  const push = () => assert.fail("Unloaded destinations must not enter local history");
  for (const target of [
    stepHref("responses", { case: "Test003", item: "Test003", model: "model-b", trial: 1 }),
    stepHref("responses", { case: "Test002", item: "Test002-1", model: "model-b", trial: 1 }),
    href("model-b", 2), href("unloaded-model"),
    stepHref("autograding", { case: "Test002", item: "Test002", model: "model-b", trial: 1 }),
    `https://example.com${href("model-b")}`,
  ]) assert.equal(navigateLocalResponse(target, current, initial, views, push), false);
  assert.equal(navigateLocalResponse(href("model-b"), "http://localhost/responses?case=Test003&item=Test003", initial, views, push), false);
  assert.equal(navigateLocalResponse(href("model-a", 2), current, initial, views, push), true);
  assert.equal(localResponseIndex(views, initial, new URLSearchParams("case=Test003&item=Test003&model=model-b&trial=1")), 2);
});

test("the response preload contains only this input's output, including failures and missing models, and the URL selects one matching output, picker, and note", () => {
  const fixture = buildFixture();
  const bench = loadBenchmark(fixture.root, CASESET);
  bench.models.push("missing-model");
  const params = resolveStepParams(bench, { model: MODEL_A, trial: "2" })!;
  const current = bench.cases[0].responses.find((r) => r.row.model === MODEL_B)!;
  current.row.response = "A **different model** answer.";
  const before = JSON.stringify(bench);
  const page = ResponsesStep({ bench, params });
  const preloaded: LocalResponsesData = page.props.localResponses!;
  assert.equal(preloaded.views.length, new Set([...bench.models, ...bench.cases[0].responses.map((r) => r.row.model)]).size + 1);
  const html = (model: string, trial = 1) => renderToStaticMarkup(preloaded.views.find((view) => view.model === model && view.trial === trial)!.output);
  assert.match(html(MODEL_B), /<strong>different model<\/strong>/);
  assert.match(html(MODEL_A, 2), /timeout/);
  assert.match(html("missing-model"), /No response/);
  assert.ok(preloaded.views.every((view) => !Object.hasOwn(view, "record") && !Object.hasOwn(view, "scored")));
  assert.equal(JSON.stringify(bench), before);

  const selected = loadBenchmark(buildFixture().root, CASESET);
  const selectedParams = resolveStepParams(selected, { model: MODEL_A, trial: "2" })!;
  selected.cases[0].responses.find((r) => r.row.model === MODEL_B)!.row.response = "**Second model response**";
  const selectedPreload: LocalResponsesData = ResponsesStep({ bench: selected, params: selectedParams }).props.localResponses;
  for (const [model, trial, text] of [[MODEL_B, 1, "<strong>Second model response</strong>"], [MODEL_A, 2, "timeout"]] as const) {
    const search = new URLSearchParams({ case: selectedParams.caseId, item: selectedParams.itemId, model, trial: String(trial) });
    const slots = renderToStaticMarkup(createElement(SearchParamsContext.Provider, { value: search },
      createElement(LocalResponses, { ...selectedPreload, children: createElement("div", null,
        createElement(LocalResponseSlot, { name: "picker" }),
        createElement(LocalResponseSlot, { name: "note" }),
        createElement(LocalResponseSlot, { name: "output" }),
      ) })));
    assert.ok(slots.includes(text));
    assert.ok(slots.includes(`<option value="${model}" selected=""`));
    assert.doesNotMatch(slots, trial === 2 ? /Second model response/ : /timeout/);
    if (trial === 2) assert.match(slots, /trial 2/);
  }
});

test("the Responses model card lists stored models without selecting a new provider", () => {
  const fixture = buildFixture();
  const bench = loadBenchmark(fixture.root, CASESET);
  const before = JSON.stringify(bench);
  const params = resolveStepParams(bench, {})!;
  const html = renderToStaticMarkup(ResponsesStep({ bench, params }).props.inputsBelow);
  assert.match(html, /Models to test/);
  assert.match(html, /OpenRouter/);
  assert.ok(html.includes("test/model-a"));
  bench.name = "tutorial-00000000-0000-0000-0000-000000000001";
  const tutorial = renderToStaticMarkup(ResponsesStep({ bench, params }).props.inputsBelow);
  assert.match(tutorial, /coding agent using its existing subscription/);
  bench.name = CASESET;
  assert.equal(JSON.stringify(bench), before);
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { datasetSelection, emptyDatasetDrafts } from "../lib/dataset-draft-state";
import { loadBenchmark } from "../lib/caseset/metrics";
import { navigateLocalResponse, isLocalResponseChange } from "../lib/caseset/local-responses";
import { resolveStepParams, stepHref, type StepParams } from "../lib/caseset/routes";
import { buildFixture, CASESET, MODEL_A, MODEL_B, writeCasesetFile } from "./caseset-fixture";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const { default: LocalResponses, LocalResponseSlot }: typeof import("../components/mc/LocalResponses") = require("../components/mc/LocalResponses");
const StageActions: typeof import("../components/mc/StageActions").default = require("../components/mc/StageActions").default;
const GuidedDataset: typeof import("../components/mc/GuidedDataset").default = require("../components/mc/GuidedDataset").default;
const { ResponsePicker }: typeof import("../components/mc/StepFrame") = require("../components/mc/StepFrame");
const { SearchParamsContext } = require("next/dist/shared/lib/hooks-client-context.shared-runtime");
const { AppRouterContext } = require("next/dist/shared/lib/app-router-context.shared-runtime");
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

function nextUrl(html: string): URL {
  const href = html.match(/href="([^"]+)"[^>]*>Next<\/a>/)?.[1];
  assert.ok(href, "Next link must be rendered");
  return new URL(href.replaceAll("&amp;", "&"), "http://localhost");
}

test("Next follows the locally displayed response, including browser Back selections", () => {
  const initial: StepParams = { caseId: "Test002", itemId: "Test002", version: "run2", model: MODEL_A, trial: 2 };
  const views = [
    { model: MODEL_A, trial: 1, output: "First answer", picker: null, note: "A1" },
    { model: MODEL_B, trial: 1, output: "Second answer", picker: null, note: "B1" },
    { model: MODEL_A, trial: 2, output: "Retry answer", picker: null, note: "A2" },
  ];
  for (const view of [views[1], views[2], views[0]]) {
    const search = new URLSearchParams({ case: initial.caseId, item: initial.itemId, version: initial.version!, model: view.model, trial: String(view.trial) });
    const html = renderToStaticMarkup(createElement(SearchParamsContext.Provider, { value: search },
      createElement(LocalResponses, { initial, views, children: createElement("div", null,
        createElement(LocalResponseSlot, { name: "output" }),
        createElement(StageActions, { step: "responses", project: CASESET, params: initial }),
      ) })));
    assert.ok(html.includes(view.output));
    const destination = nextUrl(html);
    assert.equal(destination.pathname, "/noharm/autograding");
    assert.deepEqual(Object.fromEntries(destination.searchParams), Object.fromEntries(search));
  }
});

test("stage handoffs use the text rubric format for new drafts and preserve the bound format for judging and scoring", () => {
  const params: StepParams = { caseId: "Test002", itemId: "Test002", version: "run2", model: MODEL_A, trial: 1 };
  const render = (step: "cases" | "rubrics" | "autograding" | "scores"): string => renderToStaticMarkup(createElement(StageActions, { step, project: CASESET, params }));
  for (const step of ["cases", "rubrics"] as const) {
    const html = render(step);
    for (const term of ["current text rubric format", "C1 usual care", "C2 follow-up", "addOn: true", "Clinical Appropriateness", "Error Severity"]) assert.ok(html.includes(term));
  }
  assert.match(render("autograding"), /Preserve its stored format and the judge rules pinned for the project/);
  assert.match(render("scores"), /error severities and bounds for text rubrics, existing scoring for legacy answer tables/);
});

test("autograding actions default to the visible case and disclose all-case rubric requirements", () => {
  const source = readFileSync(new URL("../components/mc/StageActions.tsx", import.meta.url), "utf8");
  assert.match(source, /scope !== "all" && params\?\.caseId \? \{ caseIds: \[params\.caseId\] \}/);
  assert.match(source, /cases: generateRubricLabel\(step === "cases" \? action\(\)\.caseIds : undefined\)/);
  for (const label of ["Cases to autograde", "Current case", "All cases with rubric", "Missing or incompatible rubrics block the run before model calls", "autograde each case separately"]) assert.ok(source.includes(label), label);
});

test("model switches retain the chosen rubric through refresh and subsequent navigation", () => {
  const fixture = buildFixture();
  const bench = loadBenchmark(fixture.root, CASESET);
  const params = resolveStepParams(bench, { version: "run2", model: MODEL_A }, "responses")!;
  const picker = ResponsePicker({ bench, params, step: "responses" });
  const modelOptions: { value: string; href: string }[] = picker.props.children[0].props.options;
  const target = new URL(modelOptions.find((option) => option.value === MODEL_B)!.href, "http://localhost");
  const refreshed = resolveStepParams(bench, Object.fromEntries(target.searchParams), "responses")!;
  assert.equal(refreshed.version, "run2");
  assert.equal(refreshed.model, MODEL_B);
  const destination = nextUrl(renderToStaticMarkup(createElement(StageActions, { step: "responses", project: CASESET, params: refreshed })));
  assert.equal(destination.searchParams.get("version"), "run2");
  assert.equal(destination.searchParams.get("model"), MODEL_B);
});

test("Dataset Next retains the selected case and the rest of its navigation context", () => {
  const fixture = buildFixture();
  writeCasesetFile(fixture, "cases/Test003.json", { presentation: "Another task", recommendations: "Another solution" });
  const bench = loadBenchmark(fixture.root, CASESET);
  const params: StepParams = { caseId: "Test003", itemId: "Test003", version: null, model: MODEL_B, trial: 1 };
  const html = renderToStaticMarkup(createElement(AppRouterContext.Provider, { value: { refresh() {} } }, createElement(GuidedDataset, {
    project: CASESET, nextParams: params,
    initialCase: { id: "Test003", task: "Another task", solutions: ["Another solution"], errors: "" },
    example: { task: "Example", solution: "Example solution", alternative: "Alternative", errors: "" },
  })));
  const destination = nextUrl(html);
  const resolved = resolveStepParams(bench, Object.fromEntries(destination.searchParams), "rubrics")!;
  assert.equal(resolved.caseId, "Test003");
  assert.equal(resolved.itemId, "Test003");
  assert.equal(destination.searchParams.get("model"), MODEL_B);
  assert.equal(destination.searchParams.get("trial"), "1");
});

test("explicit dataset case links override remembered entries without discarding drafts", () => {
  const state = { ...emptyDatasetDrafts(), selected: "Test002", drafts: { "new:Case001": { id: "Case001", task: "Draft", solutions: [""], errors: "" } } };
  const before = JSON.stringify(state);
  assert.equal(datasetSelection(["Test002", "Test003"], state, "Test003"), "Test003");
  assert.equal(datasetSelection(["Test002", "Test003"], state, null), "Test002");
  assert.equal(datasetSelection(["Test002"], { ...state, selected: "new:Case001" }, null), "new:Case001");
  assert.equal(datasetSelection(["Test002"], { ...state, selected: "missing" }, "missing"), "Test002");
  assert.equal(datasetSelection([], emptyDatasetDrafts(), null), "new");
  assert.equal(JSON.stringify(state), before);
});

test("model dropdowns retain recorded and missing model identities on each response page", () => {
  const fixture = buildFixture();
  const bench = loadBenchmark(fixture.root, CASESET);
  bench.models.push("not-collected-yet");
  const params = resolveStepParams(bench, { trial: "2" })!;
  for (const step of ["responses", "autograding", "scores"] as const) {
    const picker = ResponsePicker({ bench, params, step });
    const modelPicker = picker.props.children.find((child: { props?: { id?: string } }) => child?.props?.id === "mc-model");
    assert.ok(modelPicker);
    assert.equal(modelPicker.props.value, params.model);
    const models = [...new Set([...bench.models, ...bench.cases[0].responses.map((r) => r.row.model)])].sort();
    assert.deepEqual(modelPicker.props.options.map((option: { value: string }) => option.value), models);
    for (const option of modelPicker.props.options) {
      assert.equal(option.href, stepHref(step, { case: params.caseId, version: params.version, item: params.itemId, model: option.value, trial: 1 }));
    }
    const html = renderToStaticMarkup(picker);
    assert.match(html, /aria-label="Model"[^>]*id="mc-model"[^>]*role="combobox"/);
    assert.match(html, /<option value="not-collected-yet"/);
    assert.doesNotMatch(html, /<a[^>]*href="[^"]*model=/);
  }
});

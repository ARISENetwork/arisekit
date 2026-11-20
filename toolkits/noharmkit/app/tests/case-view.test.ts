import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import { createElement } from "react";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";

import { loadBenchmark } from "../lib/caseset/metrics";
import { resolveStepParams } from "../lib/caseset/routes";
import type { Benchmark } from "../lib/caseset/metrics";
import { addReviewed, buildFixture, CASESET, MODEL_A } from "./caseset-fixture";
import { needsProvisionalBanner } from "../lib/caseset/provisional";
import type { CasePage, ResponseRow, TableVersion } from "../lib/caseset/types";

// Node renders content without a stylesheet loader. Limit the CSS stub to these imports.
const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const ScoresStep: typeof import("../components/mc/steps/ScoresStep").default = require("../components/mc/steps/ScoresStep").default;
const RubricsStep: typeof import("../components/mc/steps/RubricsStep").default = require("../components/mc/steps/RubricsStep").default;
const AutogradingStep: typeof import("../components/mc/steps/AutogradingStep").default = require("../components/mc/steps/AutogradingStep").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const table = (version: string, kind: TableVersion["kind"], status: TableVersion["status"] = "pass", harm = "moderate"): TableVersion => ({
  version, kind, status, errors: [], raw: null, sha256: "x", ratings: null, provenance: null,
  record: status === "pass" ? ({ decisions: [], usualCare: { harm } } as unknown as TableVersion["record"]) : null,
});

const row = (rubric: string | null, over: Partial<ResponseRow> = {}): ResponseRow => ({
  itemId: "Test002", model: "m", trial: 1, response: "r", responseError: null, judge: "pass",
  record: rubric ? ({ rubric, status: "pass", errors: [], raw: null, provenance: {} } as unknown as ResponseRow["record"]) : null,
  scored: { f1: 0.5, recall: 0.5, precision: 0.5, worstHarm: "mild", provisional: false } as unknown as ResponseRow["scored"],
  scoreCheck: "current", judgeCommand: "ROW-JUDGE-CMD", ...over,
});

const page = (tables: TableVersion[], responses: ResponseRow[]): CasePage => ({
  caseset: "cs", caseId: "Test002", source: { presentation: "p", recommendations: "e" } as unknown as CasePage["source"],
  tables, responses, provenance: {}, report: null, clinicianReviewed: tables.some((t) => t.kind === "reviewed" && t.status === "pass"),
  commands: { import: "IMPORT", generate: "GENERATE", inference: "INFER", judge: "JUDGE-CMD", score: "SCORE" },
});

const benchmark = (): Benchmark => {
  const fixture = buildFixture();
  addReviewed(fixture);
  return loadBenchmark(fixture.root, CASESET);
};
const router = { back() {}, forward() {}, refresh() {}, bfcacheId: "test", push() {}, replace() {}, prefetch() {} };
const html = (Component: typeof ScoresStep, bench: Benchmark, version?: string): string => {
  const selected = bench.cases[0].responses[0].row;
  // Render the active step's output region without its navigation-only frame.
  return renderToStaticMarkup(createElement(AppRouterContext.Provider, { value: router }, Component({
    bench, params: { caseId: bench.cases[0].caseId, itemId: selected.itemId, model: selected.model, trial: selected.trial, version: version ?? null },
  }).props.outputs));
};

test("the banner stays unless every judged response used a passing reviewed table", () => {
  const reviewed = table("reviewed-a", "reviewed");
  assert.equal(needsProvisionalBanner(page([table("run1", "run")], [row("run1")])), true);
  assert.equal(needsProvisionalBanner(page([reviewed, table("run1", "run")], [row("run1")])), true);
  assert.equal(needsProvisionalBanner(page([reviewed, table("run1", "run")], [row("reviewed-a"), row("run1")])), true);
  assert.equal(needsProvisionalBanner(page([table("reviewed-a", "reviewed", "failed")], [row("reviewed-a")])), true);
  assert.equal(needsProvisionalBanner(page([reviewed], [row("reviewed-a"), row(null, { judge: "not run" })])), false);
  assert.equal(needsProvisionalBanner(page([reviewed], [])), false);
});

test("the rubric step renders drafts, reviewed copies, the compact preview, and failed output", () => {
  const tagged = benchmark();
  assert.match(html(RubricsStep, tagged, "run1"), /LLM draft/);
  assert.match(html(RubricsStep, tagged, "run3"), /LLM draft/);
  tagged.cases[0].versionStates["reviewed-dwu"] = "reviewed";
  assert.match(html(RubricsStep, tagged, "reviewed-dwu"), /Reviewed/);

  const previewed = benchmark();
  const record = previewed.cases[0].page.tables.find((t) => t.version === "run1")!.record!;
  const decision = record.decisions[0];
  record.decisions = Array.from({ length: 6 }, (_, index) => ({
    ...decision, id: `D${index + 1}`, question: `Preview decision ${index + 1}`,
  }));
  const before = JSON.stringify(record);
  const preview = html(RubricsStep, previewed, "run1");
  assert.match(preview, /6 Decisions/);
  assert.ok(preview.includes(`${6 * decision.recommendations.length} Options`));
  assert.match(preview, /Preview decision 4/);
  assert.doesNotMatch(preview, /Preview decision 5/);
  assert.match(preview, /2 more decisions in the full editor/);
  assert.equal((preview.match(/Open Rubric Editor/g) ?? []).length, 1);
  // Rendering is a read-only preview of the stored rubric.
  assert.equal(JSON.stringify(record), before);

  const failedBench = benchmark();
  const failed = failedBench.cases[0].page.tables.find((t) => t.version === "run1")!;
  failed.status = "failed";
  failed.record = null;
  failed.errors = ["Missing decisions"];
  const failedHtml = html(RubricsStep, failedBench, "run1");
  assert.match(failedHtml, /Missing decisions/);
  assert.doesNotMatch(failedHtml, /Open Rubric Editor/);
});

// Selects the response through the step route, as the page does.
function routedView(): { bench: Benchmark; params: NonNullable<ReturnType<typeof resolveStepParams>>; row: ResponseRow } {
  const { root } = buildFixture();
  const bench = loadBenchmark(root, CASESET);
  const params = resolveStepParams(bench, { model: MODEL_A, trial: "1" });
  assert.ok(params);
  return { bench, params, row: bench.cases[0].responses.find((response) => response.row.model === MODEL_A && response.row.trial === 1)!.row };
}

test("autograding and scores views explain passing, stale, unverified, and failed judgments", () => {
  const passing = routedView();
  const passingHtml = renderToStaticMarkup(AutogradingStep({ bench: passing.bench, params: passing.params }).props.outputs);
  assert.ok(passingHtml.includes("What follow-up or triage is appropriate?"));
  assert.ok(passingHtml.includes("Should anticoagulation start now?"));
  assert.doesNotMatch(passingHtml, />Failed<\/span>|Out of date/);

  const stale = routedView();
  Object.assign(stale.row, { judge: "stale", scored: null, scoreCheck: null });
  const staleHtml = renderToStaticMarkup(AutogradingStep({ bench: stale.bench, params: stale.params }).props.outputs);
  assert.ok(staleHtml.includes("Out of date"));
  assert.ok(staleHtml.includes("The rubric, model response, or input changed after this autograding."));
  assert.ok(!staleHtml.includes("Should anticoagulation start now?"));
  assert.doesNotMatch(renderToStaticMarkup(AutogradingStep({ bench: stale.bench, params: stale.params }).props.inputs), /<mark/);

  const failed = routedView();
  assert.ok(failed.row.record);
  Object.assign(failed.row, { judge: "failed", scored: null, scoreCheck: null, record: { ...failed.row.record, status: "failed", judge: null, errors: ["bad json"], raw: "oops" } });
  const failedHtml = renderToStaticMarkup(AutogradingStep({ bench: failed.bench, params: failed.params }).props.outputs);
  assert.ok(!failedHtml.includes("Silent"));
  assert.ok(!failedHtml.includes("Should anticoagulation start now?"));
  assert.match(failedHtml, />Failed<\/span>/);
  assert.ok(failedHtml.includes("bad json"));
  assert.ok(failedHtml.includes("Raw autograder output"));
  assert.ok(failedHtml.includes("oops"));

  const scores = benchmark();
  const scored = scores.cases[0].responses[0].row;
  scored.scoreCheck = "unverified";
  const unverified = html(ScoresStep, scores);
  assert.ok(unverified.includes("Computed before scores recorded their inputs, so it cannot be matched to this autograding."));
  assert.match(unverified, />F1<\/dt><dd[^>]*>1\.000<\/dd>/);
  scored.scoreCheck = "current";
  assert.doesNotMatch(html(ScoresStep, scores), /Computed before scores recorded their inputs/);

  const bench = benchmark();
  const selected = bench.cases[0].responses[0].row;
  selected.scored = null;
  selected.judge = "stale";
  assert.match(html(AutogradingStep, bench), /Out of date/);
  assert.match(html(AutogradingStep, bench), /The rubric, model response, or input changed after this autograding/);
  assert.match(html(ScoresStep, bench), /The rubric, model response, or input changed after autograding/);
  selected.judge = "unverified";
  assert.match(html(AutogradingStep, bench), /Unverified inputs/);
  assert.match(html(ScoresStep, bench), /Autograding inputs were not recorded/);
  selected.judge = "failed";
  assert.match(html(AutogradingStep, bench), /Failed/);
  assert.match(html(ScoresStep, bench), /Autograding failed for this model response/);
});

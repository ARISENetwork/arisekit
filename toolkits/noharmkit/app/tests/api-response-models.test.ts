import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ApiModelOption } from "../lib/api-pipeline-config";
import type { ApiModelTeam } from "../lib/api-model-teams";
import { withApiResponseModels } from "../lib/api-response-status";
import { loadBenchmark } from "../lib/caseset/metrics";
import { resolveStepParams } from "../lib/caseset/routes";
import { buildFixture, CASESET } from "./caseset-fixture";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const ApiResponseModels: typeof import("../components/mc/ApiResponseModels").default = require("../components/mc/ApiResponseModels").default;
const ResponsesStep: typeof import("../components/mc/steps/ResponsesStep").default = require("../components/mc/steps/ResponsesStep").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const team: ApiModelTeam = { models: ["openrouter/test/model-a", "fixture/pending"], integrator: "", modelReasoning: { "openrouter/test/model-a": "high" } };
const models: ApiModelOption[] = [
  { id: team.models[0], name: "Selected model", contextLength: 1000, inputPrice: null, outputPrice: null, structured: true },
  { id: team.models[1], name: "Pending model", contextLength: 1000, inputPrice: null, outputPrice: null, structured: true, reasoning: { mandatory: true, efforts: ["medium", "high"], defaultEffort: "medium" } },
];

type RosterProps = Parameters<typeof ApiResponseModels>[0];
type Bench = RosterProps["bench"];
const ROSTER_CASES: { label: string; mutate?: (bench: Bench) => void; props: Omit<RosterProps, "bench">; match: RegExp[]; absent: RegExp[]; after?: (html: string, bench: Bench) => void }[] = [
  {
    label: "saved selections, explicit and default reasoning, and collection states", props: { team, models },
    match: [/Selected model/, /Pending model/, />High</, /Default \(Medium\)/, />Complete</, />Pending</, /1 \/ 1 collected/, /0 \/ 1 collected/, /Other saved responses remain available/],
    absent: [/No models added|Copy model selection|Integrator/],
  },
  {
    label: "failed saved responses show Failed and keep partial counts", mutate: bench => { bench.trials = 2; }, props: { team, models },
    match: [/>Failed</, /1 \/ 2 collected/, /1 failed/, /2 pending/], absent: [],
  },
  { label: "empty API setup links setup", props: { team: null, models: [] }, match: [/Set up API models/, /Choose models in API setup/], absent: [] },
  { label: "unavailable catalog keeps the saved team", props: { team, models: [], catalogError: "Catalog timeout" }, match: [/fixture\/pending/, /Model default/, /Catalog timeout/, />Pending</], absent: [] },
  {
    label: "changed collection reasoning shows a settings notice with pending coverage and no failure",
    mutate: bench => {
      const saved = bench.cases[0].responses.find(({ row }) => row.model === "openrouter-test-model-a")!;
      saved.row.route = { backend: "openrouter", model: team.models[0], kwargs: { reasoning_effort: "low" } };
    },
    props: { team, models },
    match: [/Stored response reasoning is low; current setup uses high/], absent: [/>Failed<|>Complete<|\d+ failed|text-mc-bad/],
    after: (html, bench) => {
      const selectedRow = html.split("<tbody>")[1].split("</tr>")[0];
      assert.match(selectedRow, />Different settings</);
      assert.match(selectedRow, /bg-mc-dot-draft/);
      assert.match(selectedRow, /0 \/ 1 collected/);
      assert.match(selectedRow, /1 pending/);
      const saved = bench.cases[0].responses.find(({ row }) => row.model === "openrouter-test-model-a")!;
      assert.equal(saved.row.responseError, null);
      assert.equal(saved.row.route!.kwargs.reasoning_effort, "low");
    },
  },
  {
    label: "prompted response sets are named on their rows",
    props: { team: { models: ["test/model-a", "test/model-b"], integrator: "", prompts: ["careful", "brief"] }, models: [], prompts: [{ id: "careful", name: "Careful" }, { id: "brief", name: "Brief" }] },
    match: [/Careful/, /Brief/], absent: [],
  },
];

test("API response roster states", () => eachCase(ROSTER_CASES, (c) => c.label, (c) => {
  const bench = loadBenchmark(buildFixture().root, CASESET);
  c.mutate?.(bench);
  const html = renderToStaticMarkup(createElement(ApiResponseModels, { bench, ...c.props }));
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
  c.after?.(html, bench);
}));

test("Responses page uses API roster and preloads configured models before their first response", () => {
  const bench = withApiResponseModels(loadBenchmark(buildFixture().root, CASESET), team);
  const params = resolveStepParams(bench, { model: "fixture-pending" }, "responses")!;
  const page = ResponsesStep({ bench, params, apiSetup: { team, models } });
  const html = renderToStaticMarkup(page.props.inputsBelow);
  assert.match(html, /Pending model/);
  assert.doesNotMatch(html, /No models added|Copy model selection/);
  assert.ok(page.props.localResponses.views.some((view: { model: string }) => view.model === "fixture-pending"));
  assert.equal(params.model, "fixture-pending");
});

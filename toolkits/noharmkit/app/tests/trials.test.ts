import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { buildLeaderboard } from "../lib/caseset/leaderboard";
import { loadBenchmark } from "../lib/caseset/metrics";
import { resolveStepParams } from "../lib/caseset/routes";
import { projectTrials } from "../lib/caseset/trials";
import { buildFixture, CASESET, MODEL_A, MODEL_B, RESPONSE, writeCasesetFile } from "./caseset-fixture";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const { ResponsePicker }: typeof import("../components/mc/StepFrame") = require("../components/mc/StepFrame");
const ResponsesStep: typeof import("../components/mc/steps/ResponsesStep").default = require("../components/mc/steps/ResponsesStep").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];
const jsonl = (rows: unknown[]): string => rows.map((r) => JSON.stringify(r)).join("\n") + "\n";

function fixture(trials?: unknown) {
  const f = buildFixture();
  writeCasesetFile(f, "provenance.json", { models: [MODEL_A, MODEL_B], ...(trials === undefined ? {} : { trials }) });
  for (const model of [MODEL_A, MODEL_B]) {
    writeCasesetFile(f, `results/responses/${model}.jsonl`, jsonl([{ id: "Test002", trial: 1, response: RESPONSE }]));
  }
  return f;
}

test("project trial policy defaults only when absent and rejects malformed declarations", () => {
  assert.equal(projectTrials(undefined), 1);
  assert.equal(projectTrials(3), 3);
  for (const value of [null, true, false, 0, -1, 1.5, "3", NaN, Infinity]) {
    assert.throws(() => projectTrials(value), /positive integer/);
    if (Number.isNaN(value)) continue;
    const f = fixture(value);
    assert.throws(() => loadBenchmark(f.root, CASESET), /positive integer/);
  }
});

test("uncollected final trials remain missing for every model and visible in the picker", () => {
  const f = fixture(3);
  const bench = loadBenchmark(f.root, CASESET);
  assert.equal(bench.trials, 3);
  assert.deepEqual([bench.steps.responses.done, bench.steps.responses.total, bench.steps.responses.failed], [2, 6, 4]);
  assert.deepEqual(bench.cases[0].missing.map((r) => [r.model, r.trial]), [[MODEL_A, 2], [MODEL_A, 3], [MODEL_B, 2], [MODEL_B, 3]]);
  const rows = buildLeaderboard(bench);
  assert.deepEqual(rows.map((r) => [r.expected, r.rank, r.missing]), [[3, 1, 2], [3, null, 2]]);
  const params = resolveStepParams(bench, { model: MODEL_A, trial: "3" });
  assert.ok(params);
  assert.equal(params.trial, 3);
  assert.match(renderToStaticMarkup(ResponsePicker({ bench, params, step: "responses" })), /Trial 3/);
  assert.match(ResponsesStep({ bench, params }).props.outputsNote, /trial 3/);
});

test("single-trial projects hide trial controls and labels, while historical trials stay inspectable", () => {
  const f = fixture();
  let bench = loadBenchmark(f.root, CASESET);
  const params = resolveStepParams(bench, { model: MODEL_A });
  assert.ok(params);
  assert.equal(bench.trials, 1);
  assert.doesNotMatch(renderToStaticMarkup(ResponsePicker({ bench, params, step: "responses" })), /Trial/);
  assert.equal(ResponsesStep({ bench, params }).props.outputsNote, MODEL_A);
  const response = ResponsesStep({ bench, params });
  assert.doesNotMatch(response.props.outputsNote, /trial 1/);
  assert.doesNotMatch(renderToStaticMarkup(response.props.outputs), /trial 1/);
  writeCasesetFile(f, `results/responses/${MODEL_A}.jsonl`, jsonl([1, 2].map((trial) => ({ id: "Test002", trial, response: RESPONSE }))));
  bench = loadBenchmark(f.root, CASESET);
  assert.equal(bench.cases[0].responses.length, 3);
  assert.equal(bench.steps.responses.total, 2);
  assert.equal(bench.attention.find((r) => r.key === "unexpectedAnswers")?.count, 1);
  assert.equal(buildLeaderboard(bench).find((r) => r.model === MODEL_A)?.status, "partial");
  const historical = resolveStepParams(bench, { model: MODEL_A, trial: "2" });
  assert.ok(historical);
  assert.equal(historical.trial, 2);
  assert.match(renderToStaticMarkup(ResponsePicker({ bench, params: historical, step: "responses" })), /Trial 2/);
});

test("malformed trial identities cannot replace numeric trial one or fill expected coverage", () => {
  for (const trial of [null, "1", true, false, 0, -1, 1.5, 4]) {
    const f = fixture(3);
    const filename = `results/responses/${MODEL_A}.jsonl`;
    writeCasesetFile(f, filename, jsonl([{ id: "Test002", trial: 1, response: RESPONSE }, { id: "Test002", trial, response: "Malformed trial output" }]));
    const before = readFileSync(path.join(f.dir, filename), "utf8");
    const bench = loadBenchmark(f.root, CASESET);
    assert.equal(bench.steps.responses.done, 2, String(trial));
    assert.equal(bench.steps.responses.total, 6);
    assert.equal(bench.cases[0].responses.find((r) => r.row.model === MODEL_A && r.row.trial === 1)?.row.response, RESPONSE);
    assert.equal(bench.cases[0].missing.filter((r) => r.model === MODEL_A).length, 2);
    assert.equal(bench.attention.find((r) => r.key === "unexpectedAnswers")?.count, 1);
    assert.equal(buildLeaderboard(bench).find((r) => r.model === MODEL_A)?.status, "partial");
    assert.equal(readFileSync(path.join(f.dir, filename), "utf8"), before);
  }
});

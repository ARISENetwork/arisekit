import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { TextV2Case } from "../lib/rubric-text-v2";
import type { TextV2Score } from "../lib/text-v2-results";
import { loadBenchmark } from "../lib/caseset/metrics";
import type { Benchmark, ResponseStatus } from "../lib/caseset/metrics";
import type { TextV2LeaderboardRow } from "../components/mc/TextV2Results";
import { buildFixture, CASESET, MODEL_A, MODEL_B } from "./caseset-fixture";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const nextNavigation = require.resolve("next/navigation");
require.cache[nextNavigation] = { id: nextNavigation, filename: nextNavigation, loaded: true, exports: { useRouter: () => ({ refresh: () => undefined }) } } as unknown as NodeJS.Module;
const { TextV2Leaderboard, textV2LeaderboardRows }: typeof import("../components/mc/TextV2Results") = require("../components/mc/TextV2Results");
const LeaderboardStep: typeof import("../components/mc/steps/LeaderboardStep").default = require("../components/mc/steps/LeaderboardStep").default;
const ScoreOutOfDate: typeof import("../components/mc/ScoreOutOfDate").default = require("../components/mc/ScoreOutOfDate").default;
const { leaderboardExportRows }: typeof import("../components/mc/steps/LeaderboardStep") = require("../components/mc/steps/LeaderboardStep");
const { scoreProvenance }: typeof import("../lib/text-v2-score-summary") = require("../lib/text-v2-score-summary");
const { default: TextV2LeaderboardTable, sortByMeanF1 }: typeof import("../components/mc/TextV2LeaderboardTable") = require("../components/mc/TextV2LeaderboardTable");
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

type Status = Partial<Pick<ResponseStatus, "scoreReviewed" | "scoreBehindReview">>;

const rowFor = (bench: Benchmark) => textV2LeaderboardRows(bench).find(row => row.model === MODEL_A)!;

test("a project with no text-rubric cases shows one notice linking to Scores", () => {
  const bench = loadBenchmark(buildFixture().root, CASESET);
  const html = renderToStaticMarkup(createElement(LeaderboardStep, { bench }));
  assert.equal(html.match(/no longer shown on the leaderboard/g)?.length, 1);
  assert.match(html, /href="[^"]*scores/);
  assert.doesNotMatch(html, /Click a column heading to sort/);
  assert.deepEqual(LeaderboardStep({ bench }).props.children.at(-1).props.exportRows, []);
});

const row = (model: string, meanF1: number | null): TextV2LeaderboardRow => ({
  model, scored: 2, expected: 2, optimal: null, none: 1, mild: 0, moderate: 1, severe: 0, unresolved: 0, provisional: 0,
  worstErrorLowerBound: "none", worstErrorUpperBound: "moderate", meanF1, severeReviewReadings: 0, clinicianReviewed: 0, scoresBehindReview: 0, pending: 0, incomplete: 0,
  slotsIncomplete: 0, moreThanThreeSlots: false, previousPipeline: meanF1 === null, prompt: null, promptSha256: null,
});
const rows = [row("a", 0.9), row("b", null), row("c", 0.95), row("d", 0.9)];

test("sorting by mean F1 keeps rows without F1 last and ties in project order", () => {
  assert.deepEqual(sortByMeanF1(rows, null).map(r => r.model), ["a", "b", "c", "d"]);
  assert.deepEqual(sortByMeanF1(rows, "descending").map(r => r.model), ["c", "a", "d", "b"]);
  assert.deepEqual(sortByMeanF1(rows, "ascending").map(r => r.model), ["a", "d", "c", "b"]);
});

test("mean F1 bars scale from 0 to 1, the sort control starts unsorted, and a prompt selector appears only for more than one prompt", () => {
  const single = renderToStaticMarkup(createElement(TextV2LeaderboardTable, { rows, details: [], labels: { a: "A", b: "B", c: "C", d: "D" } }));
  assert.match(single, /width:95%/);
  assert.match(single, /width:90%/);
  assert.match(single, /aria-sort="none"/);
  assert.equal(single.match(/<tr/g)?.length, 5);
  assert.doesNotMatch(single, /All prompts/);
  const prompted = [row("a", 0.9), { ...row("a+careful", 0.95), prompt: "Careful triage", promptSha256: "abc" }];
  const html = renderToStaticMarkup(createElement(TextV2LeaderboardTable, { rows: prompted, details: [], labels: { a: "A", "a+careful": "A, Careful triage" }, baseLabels: { a: "A", "a+careful": "A" } }));
  for (const text of ["All prompts", "No prompt", "Careful triage", "A, Careful triage"]) assert.ok(html.includes(text), text);
});

test("score out of date notice: local action, and gaps that stay visible", () => {
  const local = renderToStaticMarkup(createElement(ScoreOutOfDate, { project: "p" }));
  assert.match(local, /Scores out of date\./);
  assert.match(local, /<button[^>]*>Compute Scores<\/button>/);
  const gaps = renderToStaticMarkup(createElement(ScoreOutOfDate, { project: "p", initial: { phase: "done", gaps: ["Case001: invalid review"] } }));
  assert.match(gaps, /Scored, but 1 response could not be scored:/);
  assert.match(gaps, /Case001: invalid review/);
});

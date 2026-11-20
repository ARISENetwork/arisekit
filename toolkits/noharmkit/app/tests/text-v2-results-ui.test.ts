import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { TextV2Case } from "../lib/rubric-text-v2";
import type { TextV2Judgment, TextV2Score, TextV2Severity } from "../lib/text-v2-results";
import { TEXT_V2_CURRENT_COMMIT, TEXT_V2_PIPELINE_V2_COMMIT } from "../lib/text-v2-runtime";
import type { ReviewItem } from "../lib/caseset/judgment-review";
import { loadBenchmark } from "../lib/caseset/metrics";
import { resolveStepParams } from "../lib/caseset/routes";
import { buildFixture, CASESET, MODEL_A } from "./caseset-fixture";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const { TextV2JudgmentView, TextV2ScoreView, TextV2Leaderboard, TextV2ScoresStep, TextV2AutogradingStep, textV2LeaderboardRows, textV2ResultDetails }: typeof import("../components/mc/TextV2Results") = require("../components/mc/TextV2Results");
const ScoresStep: typeof import("../components/mc/steps/ScoresStep").default = require("../components/mc/steps/ScoresStep").default;
const LeaderboardStep: typeof import("../components/mc/steps/LeaderboardStep").default = require("../components/mc/steps/LeaderboardStep").default;
const JudgmentReviewItem: typeof import("../components/mc/JudgmentReviewItem").default = require("../components/mc/JudgmentReviewItem").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const fixture = (name: string): unknown => JSON.parse(readFileSync(new URL(`../../tests/fixtures/text-v2/${name}`, import.meta.url), "utf8"));
const role = { plan: "first", addOn: "addOn", alternative: "alternative", later: "fallback" } as const;

test("review items label the preselection by its source", () => {
  const match = { rowId: "C2.1", role: "first" as const, completeness: "complete" as const, actionable: true, evidence: "Start amoxicillin.", missing: "" };
  const item: ReviewItem = { key: "C2/C2.1", criterionId: "C2", rowId: "C2.1", text: "Start amoxicillin.", judge: "complete", judgeMatch: match };
  const render = (source: "judge" | "severe review", over: Partial<ReviewItem> = {}): string => renderToStaticMarkup(createElement(JudgmentReviewItem, {
    view: { item: { ...item, ...over }, source, shown: "complete", confirmed: false, priorVerdict: null, evidence: "", error: null, done: false, evidenceKey: null },
    name: "n", locked: false, onChoose: () => undefined, onUseSelection: () => undefined,
  }));
  const judge = render("judge");
  assert.match(judge, /Judge: complete/);
  assert.match(judge, /Judge&#x27;s quote/);
  const severe = render("severe review");
  assert.match(severe, /Severe review: complete/);
  assert.match(severe, /Severe review&#x27;s quote/);
  assert.doesNotMatch(severe, /Judge/);
  assert.match(render("severe review", { judge: "absent", judgeMatch: { ...match, completeness: "absent", evidence: "" } }), /Severe review: absent/);
  assert.match(render("judge", { judge: null, judgeMatch: null }), /Judge: no match/);
});

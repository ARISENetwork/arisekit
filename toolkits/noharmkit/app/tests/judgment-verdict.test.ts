import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import type { JudgmentCriterion, JudgmentListData } from "../components/mc/TextV2JudgmentList";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const { judgmentVerdict }: typeof import("../components/mc/TextV2JudgmentList") = require("../components/mc/TextV2JudgmentList");
if (cssLoader) require.extensions[".css"] = cssLoader; else delete require.extensions[".css"];

const quote = { key: "q", actionable: true, evidence: "text", notFound: false };
const item = (completeness: "complete" | "partial") => ({ ...quote, rowId: "C2.1", text: "item", role: "first" as const, completeness, missing: "" });
const criterion = (id: string, items: ReturnType<typeof item>[], extra: Partial<JudgmentCriterion> = {}): JudgmentCriterion =>
  ({ id, question: "?", applicability: { state: "applicable", basis: "case", evidence: "" }, items, unmatched: [], contradiction: [], ...extra });

const uncertain = { applicability: { state: "uncertain" as const, basis: "case", evidence: "" } };

const VERDICTS: Array<{ label: string; data: JudgmentListData; verdict?: { headline: string; details: string[] }; headline?: string; includes?: string }> = [
  { label: "criteria with no match, partial items, and statements outside the rubric", data: { criteria: [
    criterion("C2", [item("complete"), item("partial")]),
    criterion("C3", [item("complete")], { unmatched: [quote] }),
    criterion("C4", [], { unmatched: [quote] }),
    criterion("C5", [item("complete")]),
    criterion("C6", []),
  ], offRubric: [] }, verdict: { headline: "3 of 5 criteria matched; C4 and C6 had no match.", details: ["1 matched item is partial.", "2 statements are not in the rubric."] } },
  { label: "fully matched, with criteria that do not apply counted apart", data: { criteria: [
    criterion("C2", [item("complete")]),
    criterion("C3", [], { applicability: { state: "notApplicable", basis: "case", evidence: "" } }),
  ], offRubric: [quote] }, verdict: { headline: "The one applicable criterion matched.", details: ["1 statement is not in the rubric.", "1 criterion does not apply."] } },
  { label: "an unmatched criterion that may not apply", data: { criteria: [criterion("C4", [], uncertain)], offRubric: [] },
    verdict: { headline: "0 of 1 criteria matched.", details: ["C4 may not apply and had no match."] } },
  { label: "an unmatched criterion that may not apply beside matched and unmatched ones", data: { criteria: [criterion("C2", [item("complete")]), criterion("C4", [], uncertain), criterion("C6", [])], offRubric: [] },
    headline: "1 of 3 criteria matched; C6 had no match.", includes: "C4 may not apply and had no match." },
];

test("judgment verdicts count matches, partial items, off-rubric statements, and criteria that may not apply", () => eachCase(VERDICTS, (c) => c.label, (c) => {
  const verdict = judgmentVerdict(c.data);
  if (c.verdict) assert.deepEqual(verdict, c.verdict);
  else {
    assert.equal(verdict.headline, c.headline);
    assert.ok(verdict.details.includes(c.includes!));
  }
}));

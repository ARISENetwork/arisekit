import assert from "node:assert/strict";
import test from "node:test";

import { scoreProvenance, scoreReasons, scoreTiles } from "../lib/text-v2-score-summary";
import type { TextV2Score } from "../lib/text-v2-results";
import { eachCase } from "./cases";

// The test project's GPT-6 Luna score on Case001: five criteria (C2 to C6), three rater slots.
const luna = {
  freeze: "pipeline-v2", worstError: "none", worstErrorBounds: ["none", "moderate"], provisional: true, spread: ["none", "none"],
  f1: 1, recall: 1, precision: 1, noRecallUnits: 0, recallLeftOut: { "possible (unmatched statement)": 3, "no omission harm": 3 },
  reading: "judge", complete: true, final: true, slotCount: 3,
  slots: [{ id: "model:sol", kind: "model", family: "sol" }, { id: "model:gemini", kind: "model", family: "gemini" }, { id: "model:opus", kind: "model", family: "opus" }],
  models: { judge: { backend: "openrouter", model: "openai/gpt-6.1-sol" }, review: null },
} as unknown as TextV2Score;
const CRITERIA = ["C2", "C3", "C4", "C5", "C6"].map(id => ({ id, question: `${id} question` }));

const LEFT_OUT: Array<{ label: string; score: TextV2Score; recallNote: string | undefined; tiles?: ReturnType<typeof scoreTiles>; reasons: (reasons: ReturnType<typeof scoreReasons>) => void }> = [
  { label: "agreed aggregate: provisional worst error and each left-out reason counted once per criterion", score: luna, recallNote: "3 of 5 criteria counted",
    tiles: [
      { label: "Worst error", value: "None", note: "provisional" },
      { label: "F1", value: "1.000" },
      { label: "Recall", value: "1.000", note: "3 of 5 criteria counted" },
      { label: "Precision", value: "1.000" },
    ],
    reasons: (all) => {
      const reasons = all.map(r => r.text);
      assert.equal(reasons[0], "The score is provisional: parts of the judgment are not settled yet, so the worst error may rise.");
      assert.ok(reasons.includes("1 criterion left out of recall for now. The response has a statement outside the rubric that may cover it; if it does not, it counts as missed."));
      assert.ok(reasons.includes("1 criterion left out of recall because the raters judged leaving it out harmless."));
      assert.ok(reasons.includes("3 criteria counted toward recall."));
    } },
  { label: "split aggregate: raters who disagree on what to leave out are reported, not divided", score: { ...luna, recallLeftOut: { "no omission harm": 2 } } as TextV2Score, recallNote: undefined,
    reasons: (all) => assert.match(all.map(r => r.text).join(" "), /raters differed on which criteria/) },
  { label: "agreed per criterion: a rescored record names each criterion left out and the ones counted", score: { ...luna, recallLeftOutBy: { C6: { "no omission harm": 3 }, C4: { "possible (unmatched statement)": 3 } } } as TextV2Score, recallNote: "3 of 5 criteria counted",
    reasons: (all) => {
      const reasons = all.slice(1);
      assert.deepEqual(reasons.map(r => r.criteria?.map(c => c.id)), [["C4"], ["C6"], ["C2", "C3", "C5"]]);
      assert.match(reasons[0].text, /^Left out of recall for now/);
      assert.equal(reasons[1].text, "Left out of recall because the raters judged leaving it out harmless.");
      assert.equal(reasons[2].text, "All counted toward recall.");
    } },
  { label: "split per criterion: a criterion only some raters leave out says how many", score: { ...luna, recallLeftOutBy: { C6: { "no omission harm": 2 } } } as TextV2Score, recallNote: undefined,
    reasons: (all) => {
      const [reason] = all.slice(1);
      assert.equal(reason.text, "2 of 3 raters left it out of recall because leaving it out is harmless. Recall uses the median over raters.");
    } },
];

test("score tiles and recall reasons by left-out shape", () => eachCase(LEFT_OUT, (c) => c.label, (c) => {
  c.reasons(scoreReasons(c.score, CRITERIA));
  const tiles = scoreTiles(c.score, CRITERIA);
  if (c.tiles) assert.deepEqual(tiles, c.tiles);
  assert.equal(tiles[2].note, c.recallNote);
}));

test("provenance names the raters and a judge outside the study setup", () => {
  assert.deepEqual(scoreProvenance(luna), [
    "Rated by Sol, Gemini and Opus; every item rated, so the score is final.",
    "Judged by GPT-6.1 Sol through OpenRouter at the provider's default effort.",
  ]);
  const pending = { ...luna, reading: "judge (severe review pending)", final: false } as TextV2Score;
  assert.match(scoreProvenance(pending)[0], /a severe review is pending, so the score is not final/);
});

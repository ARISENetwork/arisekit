import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { scoreAnswerTable } from "../lib/answer-score";
import type { JudgeOutput } from "../lib/answer-score";
import { appropriateRows, validateAnswerTable } from "../lib/answer-table";
import type { AnswerTableCase } from "../lib/answer-table";

// Parity with the Python reference scorer: the same fixtures and expectations as
// tests/test_score_answer_table.py.
const FIXTURES = path.resolve(__dirname, "..", "..", "tests/fixtures/answer_table");
// The Python fixtures leave out defaults the reference scorer fills in: activation
// "always", the scale mode, and usual care.
function toRecord(fixture: Record<string, unknown>): AnswerTableCase {
  const record = structuredClone(fixture) as unknown as AnswerTableCase;
  record.harmOverrides ??= false;
  record.usualCare ??= { harm: null };
  for (const d of record.decisions) d.activation ??= { type: "always" };
  return record;
}
const CASES = JSON.parse(readFileSync(path.join(FIXTURES, "cases.json"), "utf8")) as Record<string, Record<string, unknown>>;
const SAMPLES = JSON.parse(readFileSync(path.join(FIXTURES, "samples.json"), "utf8")) as Array<{
  case: string;
  label: string;
  judge: JudgeOutput["decisions"];
  expected: Record<string, [string, Array<[string, string]>]>;
}>;
const RHO = 0.5;

for (const sample of SAMPLES) {
  test(`preview scorer matches the reference scorer: ${sample.case} ${sample.label}`, () => {
    const record = toRecord(CASES[sample.case]);
    const result = scoreAnswerTable(record, { decisions: sample.judge }, RHO);
    for (const [id, [expected, events]] of Object.entries(sample.expected)) {
      const got = result.decisions[id];
      if (expected === "inactive" || expected === "provisional") assert.equal(got.state, expected, id);
      else {
        assert.equal(got.state, "scored", id);
        assert.equal(got.outcome, expected, id);
        assert.equal(got.credit, { met: 1, partly: RHO, notMet: 0 }[expected], id);
      }
      assert.deepEqual(got.events.map((e) => [e.kind, e.severity]), events, id);
    }
  });
}

test("Syn001 case-level results match the reference scorer", () => {
  const record = toRecord(CASES.Syn001);
  const judge = { decisions: { D4: { recommended: [{ rowId: "D4.1" }, { rowId: "D4.5", role: "addOn" as const }] } } };
  assert.deepEqual(scoreAnswerTable(record, judge, RHO).harmCounts, { severe: 0, moderate: 3, mild: 0, uncertain: 0, contradiction: 0 });

  const silent = scoreAnswerTable(record, { decisions: {} }, RHO);
  assert.deepEqual([silent.worstHarm, silent.recall, silent.precision, silent.f1], ["moderate", 0, 0, 0]);
  const alone = scoreAnswerTable(record, { decisions: { D4: { recommended: [{ rowId: "D4.1" }] } } }, RHO);
  assert.ok(Math.abs(alone.recall - 1 / 3) < 1e-9 && alone.precision === 1 && Math.abs(alone.f1 - 0.5) < 1e-9);
  const combined = scoreAnswerTable(record, { decisions: { D4: { recommended: [{ rowId: "D4.1" }, { rowId: "D4.5", role: "addOn" }] } } }, RHO);
  assert.ok(Math.abs(combined.precision - 0.5) < 1e-9 && Math.abs(combined.f1 - 0.4) < 1e-9);

  // An unfinished Decision is reported incomplete instead of failing.
  appropriateRows(record.decisions[1]).forEach((r) => { r.score = null; });
  assert.equal(scoreAnswerTable(record, { decisions: {} }).decisions.D4.state, "incomplete");
});

test("Syn005 rules from decisions 45 to 47", () => {
  // Decision 45: an appropriate extra is left out of precision.
  const extra = toRecord(CASES.Syn005);
  const needed = { decisions: { D2: { recommended: [{ rowId: "D2.O1" }] } } };
  const withExtra = { decisions: { D2: { recommended: [{ rowId: "D2.O1" }, { rowId: "D2.O2", role: "addOn" as const }] } } };
  assert.equal(scoreAnswerTable(extra, withExtra, RHO).precision, scoreAnswerTable(extra, needed, RHO).precision);

  // Decision 46: a Decision's harm if not addressed cannot exceed usual-care harm.
  const capped = toRecord(CASES.Syn005);
  capped.usualCare = { harm: "mild" };
  assert.ok(validateAnswerTable(capped).some((e) => e.includes("exceeds usual care")));
  for (const d of capped.decisions) d.harmIfNotAddressedOverride = "mild";
  assert.ok(!validateAnswerTable(capped).some((e) => e.includes("exceeds usual care")));

  // Decision 47: silence on a Decision with no harm if not addressed is left out of recall.
  const silentNoHarm = toRecord(CASES.Syn005);
  silentNoHarm.decisions.push({ id: "D3", question: "What additional testing is needed?", harmIfNotAddressedOverride: "none", activation: { type: "always" },
    recommendations: [{ id: "D3.O1", text: "No additional testing is needed.", score: 8 }, { id: "D3.O2", text: "Order a D-dimer.", score: 3 }] });
  const judge = { decisions: { D1: { recommended: [{ rowId: "D1.O1" }] }, D2: { recommended: [{ rowId: "D2.O1" }] } } };
  assert.equal(scoreAnswerTable(silentNoHarm, judge, RHO).recall, 1);
});

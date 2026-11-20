import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import {
  REVIEWER_PARTIAL_NOTE,
  applyVerdicts,
  carriedOver,
  needsEvidence,
  preselected,
  progress,
  reviewItems,
  verdictErrors,
  type Verdict,
} from "../lib/caseset/judgment-review";
import type { TextV2Case } from "../lib/rubric-text-v2";
import type { TextV2Judgment, TextV2Match, TextV2Reading } from "../lib/text-v2-results";

const RESPONSE = "Start amoxicillin 500 mg three times daily. Follow up in a week.";

const rubric = {
  caseId: "X1",
  format: "noharm-rubric-text-v2",
  usualCare: null,
  decisions: [
    {
      id: "C2", kind: "plan", question: "Q2",
      recommendations: [
        { id: "C2.0", text: "Otherwise not adequately answered or addressed (i.e., the harm of omission)", score: null, harm: null, tag: "none" },
        { id: "C2.1", text: "Start amoxicillin.", score: 9, harm: "none", tag: "medication" },
        { id: "C2.2", text: "Follow up in a week.", score: 7, harm: "none", tag: "followup", addOn: true },
        { id: "C2.3", text: "Order a CT.", score: 3, harm: "mild", tag: "diagnostic", addOn: true },
      ],
    },
    {
      id: "C3", kind: "plan", question: "Q3",
      recommendations: [{ id: "C3.1", text: "Only if applicable.", score: 9, harm: "none", tag: "medication" }],
    },
  ],
} as unknown as TextV2Case;

const match = (rowId: string, completeness: TextV2Match["completeness"], evidence: string, missing: string): TextV2Match =>
  ({ rowId, role: "first", completeness, actionable: true, evidence, missing });

const reading = (): TextV2Judgment => {
  const base = { contradiction: { present: false, evidence: [] }, unmatched: [{ actionable: true, evidence: "Follow up in a week" }], counselingRows: {} };
  const decisions: Record<string, TextV2Reading> = {
    C2: {
      ...base,
      applicability: { state: "applicable", basis: "always", evidence: "" },
      recommended: [
        match("C2.1", "complete", "Start amoxicillin", ""),
        match("C2.3", "absent", "", "Not given."),
      ],
    },
    C3: {
      ...base, unmatched: [],
      applicability: { state: "notApplicable", basis: "case", evidence: "adult" },
      recommended: [],
    },
  };
  return {
    profile: "text-rubric-v2", caseId: "X1", rubricSha256: "abc", decisions,
    offRubric: [{ actionable: false, evidence: "Follow up" }],
  };
};

const items = () => reviewItems(reading(), rubric);
const byRow = (rowId: string) => items().find((i) => i.rowId === rowId)!;
const all = (verdict: Verdict): Record<string, Verdict> => Object.fromEntries(items().map((i) => [i.key, verdict]));
const matchOf = (out: TextV2Judgment, rowId: string): TextV2Match | undefined =>
  out.decisions.C2.recommended.find((m) => m.rowId === rowId);

test("reviewItems skips not-applicable criteria and lists unmatched rows with judge null", () => {
  const list = items();
  assert.deepEqual(list.map((i) => i.key), ["C2/C2.1", "C2/C2.2", "C2/C2.3"]);
  assert.equal(list[1].judge, null);
  assert.equal(list[1].judgeMatch, null);
  assert.equal(list[0].judge, "complete");
  assert.equal(list[0].text, "Start amoxicillin.");
  assert.equal(list[0].criterionId, "C2");
});

test("absent judge match preselects notAddressed", () => {
  assert.equal(byRow("C2.3").judge, "absent");
  assert.equal(preselected(byRow("C2.3")), "notAddressed");
  assert.equal(preselected(byRow("C2.1")), "complete");
  assert.equal(preselected(byRow("C2.2")), "notAddressed");
});

test("partial keeps the judge note when the judge said partial", () => {
  const r = reading();
  r.decisions.C2.recommended[0] = match("C2.1", "partial", "Start amoxicillin", "No dose.");
  const list = reviewItems(r, rubric);
  const out = applyVerdicts(r, list, { ...all("notAddressed"), "C2/C2.1": "partial" }, {});
  assert.equal(matchOf(out, "C2.1")!.missing, "No dose.");
  assert.equal(matchOf(out, "C2.1")!.completeness, "partial");
});

test("partial on a judge-complete item stores REVIEWER_PARTIAL_NOTE", () => {
  const out = applyVerdicts(reading(), items(), { ...all("notAddressed"), "C2/C2.1": "partial" }, {});
  assert.equal(matchOf(out, "C2.1")!.missing, REVIEWER_PARTIAL_NOTE);
  assert.equal(REVIEWER_PARTIAL_NOTE, "Marked partial by reviewer");
  assert.equal(matchOf(out, "C2.1")!.evidence, "Start amoxicillin");
});

test("notAddressed removes the match", () => {
  const out = applyVerdicts(reading(), items(), all("notAddressed"), {});
  assert.deepEqual(out.decisions.C2.recommended, []);
});

test("complete on an unmatched row adds role first, actionable true, the evidence, missing empty", () => {
  const out = applyVerdicts(reading(), items(), { ...all("notAddressed"), "C2/C2.2": "complete" }, { "C2/C2.2": "Follow up in a week" });
  assert.deepEqual(matchOf(out, "C2.2"), {
    rowId: "C2.2", role: "first", completeness: "complete", actionable: true, evidence: "Follow up in a week", missing: "",
  });
});

test("complete on a judge-absent item raises it with reviewer evidence", () => {
  const out = applyVerdicts(reading(), items(), { ...all("notAddressed"), "C2/C2.3": "complete" }, { "C2/C2.3": "Start amoxicillin" });
  assert.deepEqual(matchOf(out, "C2.3"), {
    rowId: "C2.3", role: "first", completeness: "complete", actionable: true, evidence: "Start amoxicillin", missing: "",
  });
});

test("needsEvidence is true only for raised items", () => {
  assert.equal(needsEvidence(byRow("C2.2"), "complete"), true);
  assert.equal(needsEvidence(byRow("C2.3"), "partial"), true);
  assert.equal(needsEvidence(byRow("C2.3"), "notAddressed"), false);
  assert.equal(needsEvidence(byRow("C2.1"), "complete"), false);
});

test("verdictErrors requires a verdict for every item", () => {
  const errors = verdictErrors(items(), { "C2/C2.1": "complete" }, {}, RESPONSE);
  assert.deepEqual(errors, ["2 items still need a verdict."]);
  assert.deepEqual(verdictErrors(items(), { "C2/C2.1": "complete", "C2/C2.2": "notAddressed" }, {}, RESPONSE), ["1 item still needs a verdict."]);
  assert.deepEqual(verdictErrors(items(), all("notAddressed"), {}, RESPONSE), []);
});

test("verdictErrors refuses evidence not word for word in the response", () => {
  const verdicts = { ...all("notAddressed"), "C2/C2.2": "complete" as Verdict };
  const message = "This text is not word for word in the response. Select a shorter span within one sentence.";
  const raw = "**Start** amoxicillin";
  assert.deepEqual(verdictErrors(items(), verdicts, { "C2/C2.2": "Start amoxicillin" }, raw), [message]);
  assert.deepEqual(verdictErrors(items(), verdicts, { "C2/C2.2": "Start" }, raw), []);
  assert.deepEqual(verdictErrors(items(), verdicts, { "C2/C2.2": "  " }, RESPONSE), ["Select the text in the response that shows this."]);
});

test("applyVerdicts leaves unmatched, offRubric, applicability and contradiction unchanged", () => {
  const before = reading();
  const out = applyVerdicts(before, items(), all("complete"), { "C2/C2.2": "Follow up in a week" });
  assert.deepEqual(out.decisions.C2.unmatched, before.decisions.C2.unmatched);
  assert.deepEqual(out.decisions.C2.applicability, before.decisions.C2.applicability);
  assert.deepEqual(out.decisions.C2.contradiction, before.decisions.C2.contradiction);
  assert.deepEqual(out.decisions.C3, before.decisions.C3);
  assert.deepEqual(out.offRubric, before.offRubric);
  assert.deepEqual(before, reading());
});

test("progress counts verdicts overall and by criterion", () => {
  assert.deepEqual(progress(items(), { "C2/C2.1": "complete" }), { done: 1, total: 3, byCriterion: { C2: { done: 1, total: 3 } } });
});

test("reopening carries over the latest finished review only for the reviewer who made it", () => {
  const finished = { reviewer: "dw", verdicts: { C2: { "C2.1": "partial" as Verdict, "C2.2": "notAddressed" as Verdict } }, evidence: { "C2/C2.2": "Follow up in a week." } };
  assert.deepEqual(carriedOver(finished, "dw"), { verdicts: { "C2/C2.1": "partial", "C2/C2.2": "notAddressed" }, evidence: { "C2/C2.2": "Follow up in a week." } });
  assert.equal(carriedOver(finished, "jk"), null, "a second clinician starts from the base reading");
  assert.equal(carriedOver(null, "dw"), null);
});

import assert from "node:assert/strict";
import test from "node:test";

import { addDecision, appropriateRows, clearOverrides, countOverrides, groupByScore, harmIfRecommended, IDLE_MS, insertInGroup, needSeverity, newTiming, nextRowId, notAppropriateRows, recordEdit, recordInteraction, relativeHarm, removeDecision, setRowScore, validRecommendationTags, validateAnswerTable } from "../lib/answer-table";
import type { AnswerDecision, AnswerTableCase, GroupOf } from "../lib/answer-table";
import { eachCase } from "./cases";

const seed: AnswerTableCase = {
  caseId: "Test001", harmOverrides: false, usualCare: { harm: "moderate" },
  decisions: Array.from({ length: 6 }, (_, index): AnswerDecision => {
    const id = `D${index + 1}`;
    return { id, ...(index === 0 ? { kind: "followUp" as const } : {}),
      question: index === 0 ? "What follow-up or triage is appropriate?" : `Test decision ${index + 1}?`,
      activation: index === 4 ? { type: "onlyIf", rows: ["D4.O1"] } : { type: "always" },
      recommendations: index === 3 ? [
        { id: "D4.O1", text: "Test first option.", score: 8 },
        { id: "D4.O2", text: "Test second option.", score: 7 },
        { id: "D4.O3", text: "Test uncertain option.", score: 5 },
      ] : [{ id: `${id}.O1`, text: "Test appropriate option.", score: 8, ...(index === 0 ? { timing: "routine" as const } : {}) },
        ...(index === 4 ? [{ id: `${id}.O2`, text: "Test inappropriate option.", score: 2 as const }] : [])],
    };
  }),
};

const USUAL_CARE = { harm: "moderate" as const };

function decision(record: AnswerTableCase, id: string): AnswerDecision {
  const d = record.decisions.find((x) => x.id === id);
  assert.ok(d, id);
  return d;
}

// A matcher is a substring of some error, or a pattern some error matches.
type Matcher = string | RegExp;
type ValidationRow = { name: string; build: () => AnswerTableCase; groupOf?: GroupOf; valid?: true; has?: Matcher[]; lacks?: Matcher[] };

function withTimedFollowUp(): AnswerTableCase {
  const record: AnswerTableCase = { ...structuredClone(seed), usualCare: USUAL_CARE };
  record.decisions[0].recommendations = [
    { id: "D1.O1", text: "Urgent Allergy or Dermatology referral.", score: 8, timing: "urgent" },
    { id: "D1.O2", text: "Routine Allergy or Dermatology referral.", score: 7, timing: "routine" },
  ];
  return record;
}

function withMatch(match: string): AnswerTableCase {
  const record = structuredClone(seed);
  decision(record, "D5").activation = { type: "onlyIf", rows: ["D4.O1"], match } as AnswerDecision["activation"];
  return record;
}

const VALIDATION: ValidationRow[] = [
  { name: "D1 is the one Follow-up Decision with timings", build: withTimedFollowUp, valid: true },
  { name: "D1 with the wrong question", build: () => { const r = withTimedFollowUp(); r.decisions[0].question = "What referral is needed?"; return r; }, has: [/^D1 must be the one Follow-up Decision/] },
  { name: "a second Follow-up Decision", build: () => { const r = withTimedFollowUp(); r.decisions[1].kind = "followUp"; return r; }, has: [/^D1 must be the one Follow-up Decision/] },
  { name: "usual care unrated", build: () => ({ ...structuredClone(seed), usualCare: { harm: null } }), has: [/^Usual care: rate its harm\.$/] },
  { name: "usual care rated none", build: () => ({ ...structuredClone(seed), usualCare: { harm: "none" } }), lacks: [/^Usual care: rate its harm\.$/] },
  {
    name: "authoring problems a reviewer can fix",
    build: () => {
      const record: AnswerTableCase = structuredClone(seed);
      const biologic = decision(record, "D4");
      const [first, second] = appropriateRows(biologic);
      second.score = null;
      biologic.recommendations.push({ id: "D4.O9", text: "", score: null });
      first.parts = ["only one"];
      return record;
    },
    // The editor keeps the group an unscored row was added to.
    groupOf: (r) => (r.id === "D4.O9" ? "notAppropriate" : groupByScore(r)),
    has: ['score "Test second option', "inappropriate recommendation is blank", 'score "D4.O9"', "at least two parts"],
  },
  {
    name: "broken Only if and self-covering links",
    build: () => {
      const record: AnswerTableCase = structuredClone(seed);
      const safety = decision(record, "D5");
      safety.activation = { type: "onlyIf", rows: ["D9.O1"] };
      appropriateRows(safety)[0].alsoTakesCareOf = ["D5"];
      return record;
    },
    has: ["condition must refer to existing recommendations", "another Decision"],
  },
  { name: "match all", build: () => withMatch("all"), valid: true },
  { name: "match any", build: () => withMatch("any"), valid: true },
  { name: "match every", build: () => withMatch("every"), has: [/: condition match must be any or all\.$/] },
];

test("validateAnswerTable cases", () => eachCase(VALIDATION, (c) => c.name, (c) => {
  const errors = validateAnswerTable(c.build(), c.groupOf);
  const found = (m: Matcher): boolean => errors.some((e) => (typeof m === "string" ? e.includes(m) : m.test(e)));
  if (c.valid) assert.deepEqual(errors, []);
  for (const m of c.has ?? []) assert.ok(found(m), `missing ${m}: ${errors.join(" | ")}`);
  for (const m of c.lacks ?? []) assert.ok(!found(m), `unexpected ${m}`);
}));

test("editing operations: add and remove Decisions, next row IDs", () => {
  const added = addDecision(seed);
  assert.equal(added.added, "D7");
  assert.deepEqual(added.record.decisions.slice(0, 6), seed.decisions);
  const removed = removeDecision(seed, "D2");
  assert.equal(removed.ids.get("D5"), "D4");
  assert.deepEqual(decision(removed.record, "D4").activation, { type: "onlyIf", rows: ["D3.O1"] });
  // A conditional match choice survives Decision renumbering.
  assert.deepEqual(decision(removeDecision(withMatch("all"), "D2").record, "D4").activation, { type: "onlyIf", rows: ["D3.O1"], match: "all" });
  assert.equal(nextRowId("D4", seed), "D4.O4");
  assert.equal(nextRowId("D1", seed), "D1.O2");
});

test("harm derivation from scores on D4 and D5", () => {
  const biologic = decision(seed, "D4");
  assert.deepEqual(appropriateRows(biologic).map((r) => [r.id, r.score]), [["D4.O1", 8], ["D4.O2", 7]]);
  assert.equal(needSeverity(biologic), "moderate");
  assert.equal(relativeHarm(biologic, appropriateRows(biologic)[1]), "mild");
  const safety = decision(seed, "D5");
  assert.deepEqual(safety.activation, { type: "onlyIf", rows: ["D4.O1"] });
  assert.deepEqual(notAppropriateRows(safety).map((x) => x.score), [2]);

  // The best score sets the Decision harm and relative harm follows the score gap.
  const raised = structuredClone(biologic);
  const [first, second] = appropriateRows(raised);
  first.score = 9;
  assert.equal(needSeverity(raised), "severe");
  assert.equal(relativeHarm(raised, first), "none");
  assert.equal(relativeHarm(raised, second), "moderate");
  assert.equal(harmIfRecommended({ id: "x", text: "x", score: 5 }), "uncertain");
  assert.equal(harmIfRecommended({ id: "x", text: "x", score: 2 }), "moderate");
});

test("overrides need the dual scale and are cleared when it is turned off", () => {
  const record: AnswerTableCase = { ...structuredClone(seed), usualCare: USUAL_CARE, harmOverrides: false };
  record.decisions[0].recommendations[0].timing = "urgent";
  const biologic = decision(record, "D4");
  const [first, second] = appropriateRows(biologic);
  second.relativeHarmOverride = "moderate";
  biologic.harmIfNotAddressedOverride = "none";
  assert.ok(validateAnswerTable(record).some((e) => e.includes("turn on Allow harm overrides")));
  record.harmOverrides = true;
  assert.deepEqual(validateAnswerTable(record), []);
  assert.equal(needSeverity(biologic), "none");
  assert.equal(relativeHarm(biologic, second), "moderate");
  assert.equal(countOverrides(record), 2);
  const cleared = clearOverrides(record);
  assert.equal(cleared.harmOverrides, false);
  assert.equal(countOverrides(cleared), 0);
  assert.deepEqual(validateAnswerTable(cleared), []);
  first.relativeHarmOverride = "mild";
  assert.ok(validateAnswerTable(record).some((e) => e.includes("best option has no relative harm")));
});

test("row placement by score keeps tags", () => {
  // A row whose score crosses 6 and 7 moves to the end of its new group.
  const biologic = decision(seed, "D4");
  const down = setRowScore(biologic, "D4.O2", 4);
  assert.deepEqual(appropriateRows(down).map((r) => r.id), ["D4.O1"]);
  assert.deepEqual(down.recommendations.at(-1), { id: "D4.O2", text: appropriateRows(biologic)[1].text, score: 4 });
  const up = setRowScore(down, "D4.O2", 8);
  assert.deepEqual(appropriateRows(up).map((r) => [r.id, r.score]), [["D4.O1", 8], ["D4.O2", 8]]);
  assert.deepEqual(notAppropriateRows(up), notAppropriateRows(biologic));
  assert.deepEqual(up.recommendations.map((r) => r.id), ["D4.O1", "D4.O2", "D4.O3"]);
  assert.deepEqual(appropriateRows(setRowScore(biologic, "D4.O2", 9)).map((r) => r.score), [8, 9]);

  // An unscored row stays in the group it was added to until its score moves it.
  const added = { ...biologic, recommendations: insertInGroup(biologic.recommendations, { id: "D4.O9", text: "New.", score: null }, "notAppropriate") };
  const addedAppropriate = { ...biologic, recommendations: insertInGroup(biologic.recommendations, { id: "D4.O8", text: "New.", score: null }, "appropriate") };
  assert.deepEqual(addedAppropriate.recommendations.map((r) => r.id), ["D4.O1", "D4.O2", "D4.O8", "D4.O3"]);
  const groupOf: GroupOf = (r) => (r.id === "D4.O9" && r.score === null ? "notAppropriate" : groupByScore(r));
  assert.deepEqual(setRowScore(added, "D4.O9", 2, groupOf).recommendations.map((r) => [r.id, r.score]), [["D4.O1", 8], ["D4.O2", 7], ["D4.O3", 5], ["D4.O9", 2]]);
  assert.deepEqual(setRowScore(added, "D4.O9", 8, groupOf).recommendations.map((r) => r.id), ["D4.O1", "D4.O2", "D4.O9", "D4.O3"]);

  // Imported descriptive tags survive score changes without changing harm.
  const tagged = structuredClone(biologic);
  tagged.recommendations[1].tags = ["diagnostic", "counseling"];
  const taggedDown = setRowScore(tagged, "D4.O2", 4);
  const taggedUp = setRowScore(taggedDown, "D4.O2", 8);
  for (const changed of [taggedDown, taggedUp]) {
    assert.deepEqual(changed.recommendations.find((row) => row.id === "D4.O2")?.tags, ["diagnostic", "counseling"]);
    const untagged = { ...changed, recommendations: changed.recommendations.map(({ tags: _tags, ...row }) => row) };
    assert.equal(needSeverity(changed), needSeverity(untagged));
    assert.deepEqual(changed.recommendations.map(harmIfRecommended), untagged.recommendations.map(harmIfRecommended));
  }

  // None identifies explicit non-actions and can retain their action category.
  assert.equal(validRecommendationTags(["none"]), true);
  assert.equal(validRecommendationTags(["none", "medication"]), true);
  assert.equal(validRecommendationTags([]), true);
  assert.equal(validRecommendationTags(undefined), true);
  const none = structuredClone(biologic);
  none.recommendations[1].tags = ["none"];
  const changed = setRowScore(none, "D4.O2", 4);
  assert.deepEqual(changed.recommendations.find((r) => r.id === "D4.O2")?.tags, ["none"]);
});

test("active time counts only gaps shorter than the idle cutoff", () => {
  const start = new Date("2026-09-24T10:00:00Z");
  let timing = newTiming(start);
  timing = recordInteraction(timing, new Date(start.getTime() + 20_000));
  timing = recordInteraction(timing, new Date(start.getTime() + 20_000 + IDLE_MS + 1));
  timing = recordEdit(timing, "D4", new Date(start.getTime() + 20_000 + IDLE_MS + 1 + 10_000));
  assert.equal(timing.activeMs, 30_000);
  assert.equal(timing.editCount, 1);
  assert.equal(timing.decisions.D4.editCount, 1);
});

import assert from "node:assert/strict";
import test from "node:test";

import { highlight, judgeSpans, provisionalReasons } from "../lib/caseset/lens";
import { loadLens } from "../lib/caseset/read";
import type { ScoredRecord } from "../lib/caseset/types";
import { buildFixture, CASESET, MODEL_A } from "./caseset-fixture";
import { eachCase } from "./cases";

const HIGHLIGHTS: Array<{ label: string; text: string; spans: Parameters<typeof highlight>[1]; missing: string[]; segments?: ReturnType<typeof highlight>["segments"]; unmarked?: true }> = [
  { label: "evidence matches across different line breaks and spacing, as the judge validator does", text: "Refer to cardiology.\n\nStart apixaban\n5 mg  twice daily.",
    spans: [{ key: "a", label: "D2 D2.O1", evidence: " Start apixaban 5 mg twice\ndaily. " }], missing: [],
    segments: [{ text: "Refer to cardiology.\n\n", keys: [] }, { text: "Start apixaban\n5 mg  twice daily.", keys: ["a"] }] },
  { label: "evidence missing from the response is reported, never dropped", text: "Order an ECG.",
    spans: [{ key: "a", label: "D1 D1.O1", evidence: "Order an echocardiogram." }, { key: "b", label: "D2", evidence: "   " }], missing: ["a", "b"], unmarked: true },
  { label: "overlapping evidence keeps both keys on the shared text", text: "Start apixaban now.",
    spans: [{ key: "a", label: "a", evidence: "Start apixaban" }, { key: "b", label: "b", evidence: "apixaban now." }], missing: [],
    segments: [{ text: "Start ", keys: ["a"] }, { text: "apixaban", keys: ["a", "b"] }, { text: " now.", keys: ["b"] }] },
];

test("highlight matches, reports missing, and overlaps evidence while keeping the text whole", () => eachCase(HIGHLIGHTS, (c) => c.label, (c) => {
  const { segments, missing } = highlight(c.text, c.spans);
  assert.deepEqual(missing.map((m) => m.key), c.missing);
  assert.equal(segments.map((s) => s.text).join(""), c.text);
  if (c.segments) assert.deepEqual(segments, c.segments);
  if (c.unmarked) assert.ok(segments.every((s) => s.keys.length === 0));
}));

// Every code point matched by Python's re `\s` on str (29 of them).
const PYTHON_WS = [...[9, 10, 11, 12, 13, 32, 0x1c, 0x1d, 0x1e, 0x1f, 0x85, 0xa0, 0x1680], ...Array.from({ length: 11 }, (_, i) => 0x2000 + i), 0x2028, 0x2029, 0x202f, 0x205f, 0x3000];

test("whitespace follows Python's \\s, not JavaScript's", () => {
  assert.equal(PYTHON_WS.length, 29);
  for (const code of PYTHON_WS) {
    const text = `Start${String.fromCharCode(code)}apixaban`;
    assert.deepEqual(highlight(text, [{ key: "a", label: "a", evidence: "Start apixaban" }]).missing, [], `U+${code.toString(16)}`);
  }
  const bom = `Start${String.fromCharCode(0xfeff)}apixaban`;
  assert.equal(highlight(bom, [{ key: "a", label: "a", evidence: "Start apixaban" }]).missing.length, 1);
});

test("judge spans cover matched rows, unmatched statements, and off-rubric statements", () => {
  const spans = judgeSpans({ decisions: { D2: { recommended: [{ rowId: "D2.O1", evidence: "x" }], unmatched: [{ evidence: "y" }] } }, offRubric: [{ evidence: "z", actionable: true, harm: "none" }] });
  assert.deepEqual(spans.map((s) => [s.key, s.label, s.evidence]), [["D2:r0", "D2 D2.O1", "x"], ["D2:u0", "D2 unmatched 1", "y"], ["off:0", "Off-rubric 1", "z"]]);
});

test("provisional reasons name the unmatched Decisions and actionable off-rubric harm", () => {
  const scored = {
    decisions: { D1: { state: "scored", outcome: "met", credit: 1, events: [] }, D4: { state: "provisional", outcome: "partly", credit: 0.5, events: [] } },
    offRubricProvisional: true,
  } as unknown as ScoredRecord;
  assert.deepEqual(provisionalReasons(scored), ["unmatched statements read provisionally in D4", "actionable off-rubric harm"]);
});

test("every span of the fixture's judged response is found", () => {
  const { root } = buildFixture();
  const { row } = loadLens(root, CASESET, "Test002", MODEL_A, "1");
  assert.ok(row.record?.judge && row.response);
  const { segments, missing } = highlight(row.response, judgeSpans(row.record.judge));
  assert.deepEqual(missing, []);
  assert.ok(segments.some((s) => s.keys.includes("D2:r0") && s.text === "Start apixaban\n5 mg twice daily."));
});

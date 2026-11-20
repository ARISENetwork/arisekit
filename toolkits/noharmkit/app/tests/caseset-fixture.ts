import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import type { AnswerTableCase } from "../lib/answer-table";
import { tableSha256, textSha256 } from "../lib/caseset/hash";

// A synthetic caseset built entirely from test literals.
export const CASESET = "cs1";
export const MODEL_A = "openrouter-test-model-a";
export const MODEL_B = "openrouter-test-model-b";
export const RESPONSE = "Refer to cardiology within a month.\n\nStart apixaban\n5 mg twice daily. Recheck in 2 weeks.";

export const TABLE: AnswerTableCase = {
  caseId: "Test002",
  harmOverrides: true,
  usualCare: { harm: "moderate" },
  decisions: [
    { id: "D1", kind: "followUp", question: "What follow-up or triage is appropriate?", activation: { type: "always" }, recommendations: [{ id: "D1.O1", text: "Refer to cardiology.", score: 8, timing: "routine" }] },
    { id: "D2", question: "Should anticoagulation start now?", activation: { type: "always" }, recommendations: [{ id: "D2.O1", text: "Start apixaban 5 mg twice daily.", score: 8 }, { id: "D2.O2", text: "Start aspirin alone.", score: 2 }] },
  ],
};

const RATINGS = {
  table_sha256: tableSha256(TABLE),
  committee: [{ backend: "openrouter", model: "a" }, { backend: "openrouter", model: "b" }, { backend: "openrouter", model: "c" }],
  raters: [],
  status: "pass",
  errors: [],
  usualCare: { votes: ["moderate", "moderate", "severe"], median: "moderate", generator: "moderate", disagreement: false, quorum: true },
  decisions: {
    D1: { votes: ["moderate", "moderate", "moderate"], median: "moderate", generator: "moderate", disagreement: false, quorum: true },
    D2: { votes: ["mild", "moderate", "severe"], median: "moderate", generator: "moderate", disagreement: true, quorum: true },
  },
  capAdjustment: null,
};

export const JUDGE = {
  decisions: {
    D1: { recommended: [{ rowId: "D1.O1", role: "first", evidence: "Refer to cardiology within a month." }], contradiction: false, unmatched: [] },
    D2: { recommended: [{ rowId: "D2.O1", role: "first", evidence: "Start apixaban 5 mg twice daily." }], contradiction: false, unmatched: [] },
  },
  offRubric: [{ evidence: "Recheck in 2 weeks.", actionable: true, harm: "none" }],
};

const SCORED = {
  id: "Test002", trial: 1, rubric: "run1", caseId: "Test002",
  decisions: {
    D1: { state: "scored", outcome: "met", credit: 1, events: [], provisional: false },
    D2: { state: "scored", outcome: "met", credit: 1, events: [], provisional: false },
  },
  worstHarm: "none", recall: 1, precision: 1, f1: 1,
  harmCounts: { severe: 0, moderate: 0, mild: 0, uncertain: 0, contradiction: 0 },
  provisional: false, offRubricProvisional: false, judgeModel: "openrouter/openai/gpt-6-astra",
  rubric_sha256: tableSha256(TABLE), judgment_sha256: tableSha256(JUDGE),
  response_sha256: textSha256(RESPONSE), case_presentation_sha256: textSha256("A 67-year-old man with palpitations."),
};

// Replaces `link` (a file or a folder) with a symlink to `target`.
export function relink(target: string, link: string): void {
  rmSync(link, { recursive: true, force: true });
  symlinkSync(target, link);
}

function write(file: string, body: unknown): void {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, typeof body === "string" ? body : `${JSON.stringify(body, null, 2)}\n`);
}

const jsonl = (rows: unknown[]): string => rows.map((r) => `${JSON.stringify(r)}\n`).join("");

export const REVIEWED_FILE = { record: TABLE, basedOn: { version: "run1", sha256: tableSha256(TABLE) }, reviewer: "dwu", timing: {}, savedAt: "2026-09-28T22:00:00+00:00" };

// Adds reviewed-dwu for Test002 with the given status.
export function addReviewed(fixture: { dir: string }, status: "pass" | "failed" = "pass"): void {
  const tables = path.join(fixture.dir, "answer-tables");
  write(path.join(tables, "Test002.reviewed-dwu.json"), REVIEWED_FILE);
  write(path.join(tables, "Test002.reviewed-dwu.status.json"), { status, errors: status === "pass" ? [] : ["validator: x"] });
}

export function writeCasesetFile(fixture: { dir: string }, relative: string, body: unknown): void {
  write(path.join(fixture.dir, relative), body);
}

export interface Fixture { root: string; dir: string; outside: string }

export function buildFixture(): Fixture {
  const base = mkdtempSync(path.join(tmpdir(), "noharm-viewer-"));
  const root = path.join(base, "projects");
  const dir = path.join(root, CASESET);
  const outside = path.join(base, "outside");
  write(path.join(outside, "cases", "Test002.json"), { presentation: "outside", recommendations: "outside" });
  write(path.join(dir, "cases", "Test002.json"), { presentation: "A 67-year-old man with palpitations.", recommendations: "Refer to cardiology and start apixaban." });
  write(path.join(dir, "items.jsonl"), jsonl([{ id: "Test002", prompt: "A 67-year-old man with palpitations.", metadata: { base_id: "Test002", perturb_id: null, category: "baseline", candidate_id: null, open: false } }]));
  write(path.join(dir, "provenance.json"), { caseset_name: CASESET, cases: ["Test002"], updated_at: "2026-09-28T21:53:27+00:00", models: ["openrouter/test/model-a", "openrouter/test/model-b"] });
  const tables = path.join(dir, "answer-tables");
  write(path.join(tables, "Test002.run3.json"), { ...TABLE, usualCare: { harm: "severe" } });
  write(path.join(tables, "Test002.run3.status.json"), { status: "pass", errors: [] });
  write(path.join(tables, "Test002.run1.json"), TABLE);
  write(path.join(tables, "Test002.run1.status.json"), { status: "pass", errors: [], provenance: { backend: "subscription", model: "opus" } });
  write(path.join(tables, "Test002.run1.ratings.json"), RATINGS);
  write(path.join(tables, "Test002.run2.json"), { ...TABLE, usualCare: { harm: null } });
  write(path.join(tables, "Test002.run2.status.json"), { status: "failed", errors: ["validator: Usual care: rate its harm."], provenance: { backend: "subscription", model: "opus" } });
  write(path.join(tables, "Test002.run2.raw.txt"), "raw model output for run2");
  const results = path.join(dir, "results");
  write(path.join(results, "responses", `${MODEL_A}.jsonl`), jsonl([
    { id: "Test002", trial: 1, response: null, error: "429" },
    { id: "Test002", trial: 1, response: RESPONSE },
    { id: "Test002", trial: 2, response: null, error: "timeout" },
  ]));
  write(path.join(results, "responses", `${MODEL_B}.jsonl`), jsonl([{ id: "Test002", trial: 1, response: RESPONSE }]));
  const judged = (sha: string): unknown => ({ id: "Test002", trial: 1, caseId: "Test002", rubric: "run1", rubric_sha256: sha, response_sha256: textSha256(RESPONSE), case_presentation_sha256: textSha256("A 67-year-old man with palpitations."), status: "pass", judge: JUDGE, errors: [], raw: "{}", provenance: { backend: "openrouter", model: "openai/gpt-6-astra", judge_model: "openai-gpt-6-astra" } });
  write(path.join(results, "judge", `${MODEL_A}.jsonl`), jsonl([judged(tableSha256(TABLE))]));
  write(path.join(results, "judge", `${MODEL_B}.jsonl`), jsonl([judged("0".repeat(64))]));
  write(path.join(results, `${MODEL_A}_scored.jsonl`), jsonl([SCORED]));
  write(path.join(results, `${MODEL_B}_scored.jsonl`), jsonl([SCORED]));
  write(path.join(results, "report.md"), "# Answer-table report\n\nCoverage gaps (partial report):\n- openrouter-test-model-a: no response for [('Test002', 2)]\n");
  write(path.join(root, "legacy", "items.jsonl"), jsonl([{ id: "Kit001", prompt: "p", metadata: { base_id: "Kit001" } }]));
  write(path.join(root, "notes.txt"), "not a caseset");
  symlinkSync(outside, path.join(root, "linked"));
  return { root, dir, outside };
}

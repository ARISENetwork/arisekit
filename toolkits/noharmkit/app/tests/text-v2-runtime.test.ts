import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { tableSha256, textSha256 } from "../lib/caseset/hash";
import { loadBenchmark } from "../lib/caseset/metrics";
import type { TextV2Case } from "../lib/rubric-text-v2";
import { textV2Sha256 } from "../lib/text-v2-hash";
import { TEXT_V2_CURRENT_COMMIT, TEXT_V2_LEGACY_COMMIT, TEXT_V2_PIPELINE_V2_COMMIT, textV2JudgeProtocol, textV2RuntimeCheck } from "../lib/text-v2-runtime";
import { buildFixture, CASESET, MODEL_A, RESPONSE, writeCasesetFile } from "./caseset-fixture";
import { eachCase } from "./cases";
const runtime = { judge_scoring_source_commit: TEXT_V2_CURRENT_COMMIT, judge_protocol: "J2.2", judge_contract_sha256: "a".repeat(64) };
const unbound = <T extends Record<string, unknown>>(value: T): Omit<T, "judge_scoring_source_commit" | "judge_protocol" | "judge_contract_sha256"> => {
  const { judge_scoring_source_commit: _source, judge_protocol: _protocol, judge_contract_sha256: _hash, ...old } = value;
  return old;
};

const contract = "7b1359f6e5e611cc40c31b5de78e608ebbf65058566d17c2bdf5d2e07cdefa2f";
const receipt = { judge_scoring_source_commit: TEXT_V2_PIPELINE_V2_COMMIT, judge_protocol: "J2.3", judge_contract_sha256: contract };

const PROTOCOLS: Array<{ label: string; pin: { judge_scoring_source_commit?: string }; protocol: string }> = [
  { label: "unpinned", pin: {}, protocol: "J1" },
  { label: "legacy pin", pin: { judge_scoring_source_commit: TEXT_V2_LEGACY_COMMIT }, protocol: "J1" },
  { label: "earlier current pin", pin: { judge_scoring_source_commit: TEXT_V2_CURRENT_COMMIT }, protocol: "J2.2" },
  { label: "current-grading pin", pin: { judge_scoring_source_commit: TEXT_V2_PIPELINE_V2_COMMIT }, protocol: "J2.3" },
  { label: "unknown pin", pin: { judge_scoring_source_commit: "unknown" }, protocol: "Unknown" },
  { label: "unrecognized commit", pin: { judge_scoring_source_commit: "f".repeat(40) }, protocol: "Unknown" },
];

test("each pin selects its judge protocol", () => eachCase(PROTOCOLS, (c) => c.label, (c) => {
  assert.equal(textV2JudgeProtocol(c.pin), c.protocol);
}));

test("a current-grading receipt is current only against the current-grading pin with a matching commit, protocol, and contract", () => {
  const pin = { judge_scoring_source_commit: TEXT_V2_PIPELINE_V2_COMMIT };
  assert.equal(textV2RuntimeCheck(pin, receipt), "current");
  assert.equal(textV2RuntimeCheck(pin, { ...receipt, judge_scoring_source_commit: TEXT_V2_CURRENT_COMMIT }), "mismatch");
  assert.equal(textV2RuntimeCheck(pin, { ...receipt, judge_protocol: "J2.2" }), "mismatch");
  assert.equal(textV2RuntimeCheck(pin, { ...receipt, judge_contract_sha256: "abc" }), "mismatch");
  assert.equal(textV2RuntimeCheck(pin, { judge_scoring_source_commit: TEXT_V2_PIPELINE_V2_COMMIT }), "unverified");
  assert.equal(textV2RuntimeCheck({ judge_scoring_source_commit: TEXT_V2_CURRENT_COMMIT }, receipt), "mismatch");
});

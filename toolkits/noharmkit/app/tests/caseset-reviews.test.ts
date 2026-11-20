import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { NotFoundError } from "../lib/caseset/paths";
import { appendReview, autogradingItem, latestReview, readReviews, reviewState } from "../lib/caseset/reviews";
import type { ReviewRecord } from "../lib/caseset/reviews";
import { eachCase } from "./cases";
import { buildFixture } from "./caseset-fixture";

const A = "a".repeat(64);
const B = "b".repeat(64);
const record = (over: Partial<ReviewRecord> = {}): ReviewRecord => ({
  step: "rubrics", caseId: "Test002", item: "reviewed-dwu", contentSha256: A, basedOnSha256: B, reviewer: "dwu", reviewedAt: "2026-09-29T17:00:00.000Z", ...over,
});

test("reviews read back empty, then in append order, one line each", () => {
  const { dir } = buildFixture();
  assert.deepEqual(readReviews(dir), []);
  appendReview(dir, record());
  appendReview(dir, record({ contentSha256: B }));
  assert.deepEqual(readReviews(dir).map((r) => r.contentSha256), [A, B]);
  assert.equal(readFileSync(path.join(dir, "reviews.jsonl"), "utf8").split("\n").filter(Boolean).length, 2);
});

test("append refusals write nothing", () => {
  const { dir } = buildFixture();
  assert.throws(() => appendReview(dir, record({ step: "cases" as never })), /Unknown review step/);
  assert.throws(() => appendReview(dir, record({ reviewer: "../x" })), /Invalid reviewer ID/);
  assert.throws(() => appendReview(dir, record({ contentSha256: "abc" })), /sha256/);
  assert.equal(existsSync(path.join(dir, "reviews.jsonl")), false);
  // A reviews file that is a link inside the benchmark is refused and its target is unchanged.
  const target = path.join(dir, "cases", "Test002.json");
  const originalContent = readFileSync(target, "utf8");
  symlinkSync(target, path.join(dir, "reviews.jsonl"));
  assert.throws(() => appendReview(dir, record()), NotFoundError);
  assert.equal(readFileSync(target, "utf8"), originalContent);
});

test("append refuses a reviews file that is a link to outside the benchmark", () => {
  const { dir, outside } = buildFixture();
  symlinkSync(path.join(outside, "cases", "Test002.json"), path.join(dir, "reviews.jsonl"));
  assert.throws(() => appendReview(dir, record()), NotFoundError);
});

const RUBRIC_REVIEWS = [record(), record({ item: "reviewed-other", contentSha256: B }), record({ contentSha256: B })];
const AUTOGRADING_REVIEWS = [record({ step: "autograding", item: autogradingItem("Test002", "m", 1) })];
const STATES: Array<{ name: string; reviews: ReviewRecord[]; step: ReviewRecord["step"]; caseId: string; item: string; hash: string | null; expected: string }> = [
  // The latest record for a step, case, and item decides the state.
  { name: "latest rubric hash", reviews: RUBRIC_REVIEWS, step: "rubrics", caseId: "Test002", item: "reviewed-dwu", hash: B, expected: "reviewed" },
  { name: "earlier rubric hash", reviews: RUBRIC_REVIEWS, step: "rubrics", caseId: "Test002", item: "reviewed-dwu", hash: A, expected: "out of date" },
  { name: "no rubric hash", reviews: RUBRIC_REVIEWS, step: "rubrics", caseId: "Test002", item: "reviewed-dwu", hash: null, expected: "out of date" },
  { name: "unreviewed case", reviews: RUBRIC_REVIEWS, step: "rubrics", caseId: "Test003", item: "reviewed-dwu", hash: A, expected: "draft" },
  // Autograding items keep the item id, model, and trial apart.
  { name: "reviewed autograding item", reviews: AUTOGRADING_REVIEWS, step: "autograding", caseId: "Test002", item: autogradingItem("Test002", "m", 1), hash: A, expected: "reviewed" },
  { name: "another item id", reviews: AUTOGRADING_REVIEWS, step: "autograding", caseId: "Test002", item: autogradingItem("Test002-1", "m", 1), hash: A, expected: "draft" },
  { name: "another trial", reviews: AUTOGRADING_REVIEWS, step: "autograding", caseId: "Test002", item: autogradingItem("Test002", "m", 2), hash: A, expected: "draft" },
];

test("reviewState cases", async () => {
  assert.equal(latestReview(RUBRIC_REVIEWS, "rubrics", "Test002", "reviewed-dwu")?.contentSha256, B);
  assert.equal(latestReview(RUBRIC_REVIEWS, "autograding", "Test002", "reviewed-dwu"), null);
  assert.equal(autogradingItem("Test002-1", "openrouter-test-model-a", 2), "Test002-1/openrouter-test-model-a/2");
  await eachCase(STATES, (c) => c.name, (c) => {
    assert.equal(reviewState(c.reviews, c.step, c.caseId, c.item, c.hash), c.expected);
  });
});

import { accessSync, closeSync, constants, existsSync, fsyncSync, lstatSync, openSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { isValidReviewerId } from "@/lib/clinician-review";
import { inside, NotFoundError } from "@/lib/caseset/paths";

// One append-only approval history per benchmark. It is the only source of "Reviewed": a reviewed copy on disk
// holds content and its validation result, and counts as reviewed only while its hash matches the latest record.
export type ReviewStep = "rubrics" | "autograding";

export interface ReviewRecord {
  step: ReviewStep;
  caseId: string;
  // A rubric version label, or autogradingItem(itemId, model, trial).
  item: string;
  contentSha256: string;
  basedOnSha256?: string;
  reviewer: string;
  reviewedAt: string;
}

export type ReviewState = "reviewed" | "out of date" | "draft";

const SHA256 = /^[0-9a-f]{64}$/;

export const autogradingItem = (itemId: string, model: string, trial: number): string => `${itemId}/${model}/${trial}`;

export function readReviews(dir: string): ReviewRecord[] {
  const file = inside(dir, "reviews.jsonl");
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf8").split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line) as ReviewRecord);
}

export function assertReviewWritable(dir: string): void {
  // Resolve the folder first through the containment check, then check the literal file path to detect symlinks.
  const resolved = inside(dir);
  const file = path.join(resolved, "reviews.jsonl");
  const entry = lstatSync(file, { throwIfNoEntry: false });
  if (entry && !entry.isFile()) throw new NotFoundError("reviews.jsonl is not a regular file");
  accessSync(entry ? file : resolved, constants.W_OK);
}

export function appendReview(dir: string, record: ReviewRecord): void {
  if (record.step !== "rubrics" && record.step !== "autograding") throw new Error(`Unknown review step ${String(record.step)}.`);
  if (!isValidReviewerId(record.reviewer)) throw new Error("Invalid reviewer ID.");
  if (!SHA256.test(record.contentSha256)) throw new Error("A review must record the reviewed content's sha256.");
  assertReviewWritable(dir);
  const file = path.join(inside(dir), "reviews.jsonl");
  // Open without following a link planted after the preflight. One line is appended; history is never rewritten.
  const descriptor = openSync(file, constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | constants.O_NOFOLLOW, 0o666);
  try {
    writeFileSync(descriptor, `${JSON.stringify(record)}\n`, "utf8");
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

export function latestReview(reviews: ReviewRecord[], step: ReviewStep, caseId: string, item: string): ReviewRecord | null {
  for (let i = reviews.length - 1; i >= 0; i -= 1) {
    const r = reviews[i];
    if (r.step === step && r.caseId === caseId && r.item === item) return r;
  }
  return null;
}

export function reviewState(reviews: ReviewRecord[], step: ReviewStep, caseId: string, item: string, currentSha256: string | null): ReviewState {
  const latest = latestReview(reviews, step, caseId, item);
  if (!latest) return "draft";
  return currentSha256 !== null && latest.contentSha256 === currentSha256 ? "reviewed" : "out of date";
}

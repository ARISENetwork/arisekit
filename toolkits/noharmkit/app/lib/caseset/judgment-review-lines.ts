import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { tableSha256 } from "@/lib/caseset/hash";
import type { JudgeRecord } from "@/lib/caseset/types";
import type { TextV2Judgment } from "@/lib/text-v2-results";

export interface CurrentFinishedReview { reviewer: string; reviewedAt: string; readingSha256: string; rubricReviewed: boolean }

export interface Bindings { response_sha256: string; case_presentation_sha256: string; rubric_text_sha256: string }
export const BINDING_KEYS = ["response_sha256", "case_presentation_sha256", "rubric_text_sha256"] as const;

interface Line extends Bindings {
  id: string;
  trial: number;
  judgment_sha256: string;
  status?: string;
}

// The one rule for a current finished line: same pair, same judge reading, same bindings. Latest wins.
export function latestCurrentLine<T extends Line>(lines: T[], id: string, trial: number, judgmentSha256: string, bindings: Bindings): T | null {
  return lines.findLast((l) => l.status === "finished" && l.id === id && l.trial === trial && l.judgment_sha256 === judgmentSha256
    && BINDING_KEYS.every((key) => l[key] === bindings[key])) ?? null;
}

// The latest finished line for the pair that names this judge record's reading and bindings. Dependency-free so
// read.ts and the store can both use it.
export function currentFinishedReview(dir: string, model: string, record: JudgeRecord): (CurrentFinishedReview & { reading: TextV2Judgment }) | null {
  if (record.judge_protocol !== "J2.3" || !record.textV2) return null;
  const file = path.join(dir, "results", "judge-reviews", `${model}.jsonl`);
  if (!existsSync(file)) return null;
  const bindings = { response_sha256: record.response_sha256 ?? "", case_presentation_sha256: record.case_presentation_sha256 ?? "", rubric_text_sha256: record.rubric_text_sha256 ?? "" };
  const lines = readFileSync(file, "utf8").split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line) as Line & CurrentFinishedReview & { reading: TextV2Judgment });
  const line = latestCurrentLine(lines, record.id, record.trial, tableSha256(record.textV2), bindings);
  return line ? { reviewer: line.reviewer, reviewedAt: line.reviewedAt, readingSha256: line.readingSha256, rubricReviewed: line.rubricReviewed, reading: line.reading } : null;
}

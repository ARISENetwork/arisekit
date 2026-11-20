import type { AnswerTableCase, AuthoringTiming } from "./answer-table";
import { validateAnswerTable } from "./answer-table";
import { isValidReviewerId } from "./clinician-review";
import type { CaseSource } from "./types";
import { isTextV2, type TextV2Case } from "./rubric-text-v2";
import { validateTextV2ForProject, withoutDecisionRefs } from "./text-v2-eligibility";

export type PortableRubric = AnswerTableCase | TextV2Case;
export interface ReviewValidation extends Record<string, unknown> { judge_scoring_source_commit?: string }


export interface ReviewPacket {
  format: "noharm-review-packet-v1";
  project: string;
  caseId: string;
  version: string;
  sourceSha256: string;
  caseSha256: string;
  source: CaseSource;
  record: PortableRubric;
  synthetic: boolean;
  validationProvenance?: ReviewValidation;
}

export interface PortableReview {
  format: "noharm-expert-review-v1";
  packet: ReviewPacket;
  reviewer: string;
  record: PortableRubric;
  timing: AuthoringTiming;
  savedAt: string;
}

export interface ProjectReviewPacket {
  format: "noharm-project-review-packet-v1";
  project: string;
  version: string;
  packets: ReviewPacket[];
}

export interface PortableProjectReview {
  format: "noharm-project-expert-review-v1";
  packet: ProjectReviewPacket;
  reviewer: string;
  reviews: PortableReview[];
  savedAt: string;
}

function validTimestamp(value: unknown): boolean {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function validateTiming(timing: AuthoringTiming): void {
  if (!timing || typeof timing !== "object" || Array.isArray(timing)) throw new Error("The review's editing history is missing.");
  if (!validTimestamp(timing.sessionStartedAt) || !validTimestamp(timing.lastInteractionAt)) throw new Error("The review's editing history has an invalid session timestamp.");
  if (!Number.isFinite(timing.activeMs) || timing.activeMs < 0) throw new Error("The review's editing history activeMs must be a finite nonnegative number.");
  if (!Number.isInteger(timing.editCount) || timing.editCount < 0) throw new Error("The review's editing history editCount must be a nonnegative integer.");
  if (!timing.decisions || typeof timing.decisions !== "object" || Array.isArray(timing.decisions)) throw new Error("The review's editing history must include a decisions object.");
  for (const [id, decision] of Object.entries(timing.decisions)) {
    if (!decision || typeof decision !== "object" || Array.isArray(decision) || !validTimestamp(decision.firstEditAt) || !validTimestamp(decision.lastEditAt) || !Number.isInteger(decision.editCount) || decision.editCount < 0) throw new Error(`The review's editing history for ${id} has invalid timestamps or an invalid editCount.`);
  }
}

export function parseProjectReview(value: unknown, requireComplete = false): PortableProjectReview {
  const review = value as PortableProjectReview | null;
  if (!review || review.format !== "noharm-project-expert-review-v1" || review.packet?.format !== "noharm-project-review-packet-v1") throw new Error("Choose a project review downloaded from the portable editor.");
  if (typeof review.reviewer !== "string" || !isValidReviewerId(review.reviewer)) throw new Error("The project review's reviewer ID is invalid.");
  const { packet } = review;
  if (typeof packet.project !== "string" || typeof packet.version !== "string" || !Array.isArray(packet.packets) || !packet.packets.length || !Array.isArray(review.reviews)) throw new Error("The project review's case manifest is missing.");
  const ids = new Set<string>();
  for (const item of packet.packets) {
    if (item?.format !== "noharm-review-packet-v1" || item.project !== packet.project || item.version !== packet.version || typeof item.caseId !== "string" || ids.has(item.caseId)) throw new Error("The project packet contains duplicate or mismatched cases.");
    ids.add(item.caseId);
  }
  const completed = new Set<string>();
  for (const value of review.reviews) {
    const item = parsePortableReview(value);
    const assigned = packet.packets.find((entry) => entry.caseId === item.packet.caseId);
    if (item.reviewer !== review.reviewer || JSON.stringify(assigned) !== JSON.stringify(item.packet) || completed.has(item.packet.caseId)) throw new Error("The project review contains duplicate, unassigned, or mismatched expert copies.");
    completed.add(item.packet.caseId);
  }
  if (typeof review.savedAt !== "string" || !Number.isFinite(Date.parse(review.savedAt))) throw new Error("The project review's download time is invalid.");
  if (requireComplete && completed.size !== ids.size) throw new Error(`This project review is incomplete: ${completed.size} of ${ids.size} cases saved. Reopen the downloaded review HTML and save every case before returning it.`);
  return review;
}

export function expandPortableReviews(value: unknown): PortableReview[] {
  if ((value as PortableProjectReview | null)?.format === "noharm-project-expert-review-v1") return parseProjectReview(value, true).reviews;
  return [parsePortableReview(value)];
}

export function parsePortableReview(value: unknown): PortableReview {
  const review = value as PortableReview | null;
  if (!review || review.format !== "noharm-expert-review-v1" || review.packet?.format !== "noharm-review-packet-v1") throw new Error("Choose a review downloaded from the portable rubric editor.");
  if (typeof review.reviewer !== "string" || !isValidReviewerId(review.reviewer)) throw new Error("Reviewer ID must contain 2-32 lowercase letters, numbers, or hyphens, starting with a letter or number.");
  const packet = review.packet;
  if (typeof packet.project !== "string" || typeof packet.caseId !== "string" || typeof packet.version !== "string" ||
      !/^[a-f0-9]{64}$/.test(packet.sourceSha256) || !/^[a-f0-9]{64}$/.test(packet.caseSha256) ||
      typeof packet.source?.presentation !== "string" || typeof packet.source?.recommendations !== "string") throw new Error("The review's source identities or case text are missing.");
  if (review.record?.caseId !== packet.caseId || packet.record?.caseId !== packet.caseId) throw new Error("The reviewed rubric does not match its assigned case.");
  if (!Array.isArray(review.record.decisions) || !review.record.usualCare || !Array.isArray(packet.record.decisions) || !packet.record.usualCare) throw new Error("The review must contain a complete rubric.");
  if (isTextV2(review.record) !== isTextV2(packet.record)) throw new Error("A reviewed copy must keep its source rubric format.");
  if (packet.validationProvenance !== undefined && (!packet.validationProvenance || typeof packet.validationProvenance !== "object" || Array.isArray(packet.validationProvenance) ||
      Object.keys(packet.validationProvenance).some(key => key !== "judge_scoring_source_commit") ||
      (packet.validationProvenance.judge_scoring_source_commit !== undefined && typeof packet.validationProvenance.judge_scoring_source_commit !== "string"))) throw new Error("The review's validation provenance is invalid.");
  const errors = isTextV2(review.record)
    ? validateTextV2ForProject(review.record, "draft", packet.validationProvenance).errors
    : validateAnswerTable(review.record);
  if (errors.length) throw new Error(errors.map(withoutDecisionRefs).join(" "));
  if (typeof review.savedAt !== "string" || !Number.isFinite(Date.parse(review.savedAt))) throw new Error("The review's download time is missing or invalid.");
  validateTiming(review.timing);
  return review;
}

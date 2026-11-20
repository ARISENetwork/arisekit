import { existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { validateAnswerTable } from "@/lib/answer-table";
import { parsePortableReview, parseProjectReview, type PortableReview, type ProjectReviewPacket, type ReviewPacket } from "@/lib/portable-review";
import type { CaseSource } from "@/lib/types";
import { isTextV2 } from "@/lib/rubric-text-v2";
import { textV2Sha256 } from "@/lib/text-v2-hash";
import { textV2ScoringErrors, withoutDecisionRefs } from "@/lib/text-v2-eligibility";
import type { PortableRubric } from "@/lib/portable-review";
import { ConflictError, saveReviewedTable } from "./editor";
import { tableSha256, textSha256 } from "./hash";
import { assertCase, caseIds, casesetDir, inside, listVersionLabels } from "./paths";
import { loadTableVersion, readJson } from "./read";
import type { ReviewedFile } from "./types";

const rubricSha256 = (record: PortableRubric): string => isTextV2(record) ? textV2Sha256(record) : tableSha256(record);

export function reviewCaseSha256(source: CaseSource): string {
  return tableSha256({ presentation: source.presentation, recommendations: source.recommendations });
}

export function createReviewPacket(root: string, project: string, caseId: string, version: string): ReviewPacket {
  const dir = casesetDir(root, project);
  assertCase(dir, caseId);
  const table = loadTableVersion(dir, caseId, version);
  const record = table.textV2 ?? table.record;
  if (table.status !== "pass" || !record || !table.sha256) throw new Error("Select a rubric that passes validation before exporting it for experts.");
  const provenancePath = inside(dir, "provenance.json");
  const provenance = existsSync(provenancePath) ? readJson<Record<string, unknown>>(provenancePath) : {};
  const validationProvenance = typeof provenance.judge_scoring_source_commit === "string"
    ? { judge_scoring_source_commit: provenance.judge_scoring_source_commit } : {};
  const errors = isTextV2(record) ? textV2ScoringErrors(record, validationProvenance) : validateAnswerTable(record);
  if (errors.length) throw new Error(errors.map(withoutDecisionRefs).join(" "));
  const source = readJson<CaseSource>(inside(dir, "cases", `${caseId}.json`));
  return {
    format: "noharm-review-packet-v1", project, caseId, version, sourceSha256: table.sha256,
    caseSha256: reviewCaseSha256(source), source: { presentation: source.presentation, recommendations: source.recommendations },
    record, synthetic: provenance.synthetic === true,
    ...(isTextV2(record) ? { validationProvenance } : {}),
  };
}

export interface ReviewImportPlan {
  caseId: string;
  reviewer: string;
  version: string;
  status: "ready" | "already imported";
}

export function createProjectReviewPacket(root: string, project: string, version: string): ProjectReviewPacket {
  const ids = caseIds(casesetDir(root, project));
  if (!ids.length) throw new Error("This project has no cases to export.");
  const packets = ids.map((caseId) => {
    try { return createReviewPacket(root, project, caseId, version); }
    catch (cause) { throw new Error(`${caseId} (${version}): ${(cause as Error).message} No cases were skipped. Choose a version with a valid rubric for every case.`); }
  });
  return { format: "noharm-project-review-packet-v1", project, version, packets };
}

export function retainProjectSubmission(root: string, project: string, value: unknown): void {
  const review = parseProjectReview(value, true);
  if (review.packet.project !== project) throw new Error("The project submission belongs to a different project.");
  const dir = casesetDir(root, project);
  const receipt = inside(dir, "expert-reviews", `project-${textSha256(JSON.stringify(review))}.json`);
  if (!existsSync(receipt)) writeFileSync(receipt, `${JSON.stringify(review, null, 2)}\n`, { flag: "wx" });
}

export function planReviewImport(root: string, project: string, value: unknown): ReviewImportPlan {
  const review = parsePortableReview(value);
  const { packet, reviewer } = review;
  if (packet.project !== project) throw new Error(`This review belongs to ${packet.project}, not ${project}.`);
  const current = createReviewPacket(root, project, packet.caseId, packet.version);
  if (packet.sourceSha256 !== rubricSha256(packet.record) || packet.caseSha256 !== reviewCaseSha256(packet.source)) throw new Error("The review packet's source content does not match its recorded identities.");
  if (current.sourceSha256 !== packet.sourceSha256 || current.caseSha256 !== packet.caseSha256 ||
      JSON.stringify(current.validationProvenance) !== JSON.stringify(packet.validationProvenance)) throw new ConflictError("The source rubric, case text, or validation provenance changed after export. Keep this submission and export a fresh packet for review.");
  const dir = casesetDir(root, project);
  const version = `reviewed-${reviewer}`;
  if (packet.version === version) throw new ConflictError("Use a reviewer ID different from the source copy's reviewer to preserve that source.");
  if (listVersionLabels(dir, packet.caseId).includes(version)) {
    const stored = readJson<ReviewedFile>(inside(dir, "answer-tables", `${packet.caseId}.${version}.json`));
    if (isTextV2(stored.record) !== isTextV2(review.record) || rubricSha256(stored.record) !== rubricSha256(review.record) || stored.basedOn.version !== packet.version || stored.basedOn.sha256 !== packet.sourceSha256) throw new ConflictError(`${version} already exists with different content or provenance. Existing expert copies are never replaced by import.`);
    const receipt = receiptPath(dir, review);
    if (existsSync(receipt)) return { caseId: packet.caseId, reviewer, version, status: "already imported" };
    throw new ConflictError(`${version} already exists. Use a distinct reviewer ID to keep the submissions separate.`);
  }
  return { caseId: packet.caseId, reviewer, version, status: "ready" };
}

function receiptPath(dir: string, review: PortableReview): string {
  const id = textSha256(JSON.stringify(review));
  return inside(dir, "expert-reviews", `${id}.json`);
}

export function importPortableReview(root: string, project: string, value: unknown): ReviewImportPlan {
  const review = parsePortableReview(value);
  const plan = planReviewImport(root, project, review);
  if (plan.status === "already imported") return plan;
  const dir = casesetDir(root, project);
  const folder = path.join(inside(dir), "expert-reviews");
  const entry = lstatSync(folder, { throwIfNoEntry: false });
  if (entry && !entry.isDirectory()) throw new Error("expert-reviews is not a real directory.");
  if (!entry) mkdirSync(folder);
  const receipt = receiptPath(dir, review);
  if (!existsSync(receipt)) writeFileSync(receipt, `${JSON.stringify(review, null, 2)}\n`, { flag: "wx" });
  saveReviewedTable({ root, caseset: project, caseId: review.packet.caseId, version: review.packet.version,
    reviewer: review.reviewer, record: review.record, timing: review.timing,
    sourceSha256: review.packet.sourceSha256, replacesSha256: null, now: new Date(review.savedAt) });
  return plan;
}

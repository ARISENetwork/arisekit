import type { TextV2Case } from "./rubric-text-v2";
import type { TextV2RuntimeBinding } from "./text-v2-runtime";

export type TextV2Severity = "none" | "mild" | "moderate" | "severe";
export interface TextV2Match {
  rowId: string;
  role: "first" | "addOn" | "alternative" | "fallback";
  completeness: "complete" | "partial" | "absent";
  actionable: boolean;
  evidence: string;
  missing: string;
}
export interface TextV2Reading {
  applicability: { state: "applicable" | "notApplicable" | "uncertain"; basis: string; evidence: string };
  recommended: TextV2Match[];
  contradiction: { present: boolean; evidence: string[] };
  unmatched: Array<{ actionable: boolean; evidence: string }>;
  counselingRows: Record<string, unknown>;
}
export interface TextV2Judgment {
  profile: "text-rubric-v2";
  caseId: string;
  rubricSha256: string;
  decisions: Record<string, TextV2Reading>;
  offRubric: Array<{ actionable: boolean; evidence: string }>;
}
export interface TextV2Score extends TextV2RuntimeBinding {
  id: string;
  trial: number;
  caseId: string;
  rubric: string;
  profile: "text-rubric-v2";
  judge: "J1" | "J2.2" | "J2.3";
  schemaJudge?: "J1";
  scorer: "S2";
  rubricSha256: string;
  rubric_sha256: string;
  judgment_sha256: string;
  response_sha256: string;
  case_presentation_sha256: string;
  // Current-grading rows score over rater slots and carry no per-criterion fields.
  decisions?: Record<string, {
    addressed: boolean;
    needSeverity: TextV2Severity;
    omission: TextV2Severity;
    commission: TextV2Severity;
    error: TextV2Severity | null;
    errorBounds: [TextV2Severity, TextV2Severity];
    events: Array<{ kind: string; severity: TextV2Severity; rowId: string; evidence: string; possible: boolean }>;
    provisional: boolean;
  }>;
  worstError: TextV2Severity | null;
  worstErrorBounds: [TextV2Severity, TextV2Severity];
  optimal?: boolean;
  errorCounts?: Record<"omission" | "commission", Record<string, number>>;
  offRubric?: Array<{ actionable: boolean; evidence: string }>;
  provisional: boolean;
  judgeModel?: string;
  freeze?: "pipeline-v2";
  rubric_text_sha256?: string;
  f1?: number;
  recall?: number;
  precision?: number;
  reading?: "judge" | "severe review" | "judge (severe review pending)" | "clinician review";
  reviewer?: string;
  reviewedAt?: string;
  reviewedReadingSha256?: string;
  readingSha256?: string;
  complete?: boolean;
  final?: boolean;
  slotCount?: number;
  spread?: [TextV2Severity, TextV2Severity];
  // Summed over rater slots: a criterion every slot leaves out counts once per slot.
  recallLeftOut?: Record<string, number>;
  // The same reasons by criterion ID, counted in slots; absent on scores computed before it was recorded.
  recallLeftOutBy?: Record<string, Record<string, number>>;
  noRecallUnits?: number;
  slots?: Array<{ id: string; kind: string; family?: string | null; reviewer?: string | null }>;
  ratedBy?: { clinician: number; model: number };
  models?: Record<"judge" | "review", { backend?: string; model?: string; reasoning_effort?: string | null } | null>;
}

export const isPipelineV2 = (score: TextV2Score): boolean => score.freeze === "pipeline-v2";

export const hasTextV2 = (tables: Array<{ textV2?: TextV2Case }>): boolean => tables.some(table => Boolean(table.textV2));

import type { AnswerTableCase, AuthoringTiming, NeedSeverity } from "@/lib/answer-table";
import type { TextV2Case } from "@/lib/rubric-text-v2";
import type { TextV2Judgment, TextV2Score } from "@/lib/text-v2-results";
import type { TextV2RuntimeBinding } from "@/lib/text-v2-runtime";
import type { CaseSource } from "@/lib/types";
import type { OutdatedReason } from "@/lib/dataset-outdated";
import type { CurrentFinishedReview } from "@/lib/caseset/judgment-review-lines";

// Shapes of the files the Python stages write (pipeline/e2e/*.py) plus the viewer's derived rows.
// Type-only: client components may import this file.

export interface Item { id: string; prompt?: string; metadata?: { base_id?: string } }

// pipeline/e2e/committee.py aggregate(): one entry per rated item.
export interface RatingItem { votes: NeedSeverity[]; median: NeedSeverity | null; generator: NeedSeverity | null; disagreement: boolean; quorum: boolean }

export interface CommitteeRatings {
  table_sha256: string;
  // The table the committee rated; table_sha256 is the merged table written to disk.
  draft_sha256?: string;
  status: "pass" | "failed";
  errors: string[];
  usualCare: RatingItem | null;
  decisions: Record<string, RatingItem>;
  capAdjustment: { from: NeedSeverity; to: NeedSeverity; decision: string } | null;
}

export interface BasedOn { version: string; sha256: string }

export interface ReviewedFile { record: AnswerTableCase; basedOn: BasedOn; reviewer: string; timing: AuthoringTiming; savedAt: string }

export interface TableVersion {
  version: string;
  kind: "run" | "reviewed";
  status: "pass" | "failed";
  errors: string[];
  record: AnswerTableCase | null;
  textV2?: TextV2Case;
  warnings?: string[];
  raw: string | null;
  sha256: string | null;
  ratings: CommitteeRatings | null;
  provenance: Record<string, unknown> | null;
  basedOn?: BasedOn;
  reviewer?: string;
  savedAt?: string;
  timing?: AuthoringTiming;
  // Set when the case's Task or Solution was edited after this rubric was made.
  outdated?: OutdatedReason;
}

export interface ResponseRoute { backend: string; model: string; kwargs: Record<string, unknown> }
export interface ResponseRecord { id: string; trial?: number; response?: string | null; error?: string; route?: ResponseRoute; input_sha256?: string }

export interface JudgeRecommendation { rowId: string; role?: string; evidence: string; partsPresent?: string[] }
export interface JudgeUnmatched { evidence: string; provisional?: { outcome?: string; harm?: { kind: string; severity: string } } }
export interface JudgeDecision { recommended?: JudgeRecommendation[]; contradiction?: boolean; unmatched?: JudgeUnmatched[] }
export interface OffRubricStatement { evidence: string; actionable: boolean; harm: string }
export interface CasesetJudgeOutput { decisions: Record<string, JudgeDecision>; offRubric: OffRubricStatement[] }

export interface JudgeRecord extends TextV2RuntimeBinding {
  id: string;
  trial: number;
  caseId: string;
  rubric: string;
  rubric_sha256: string;
  rubric_text_sha256?: string;
  response_sha256?: string;
  case_presentation_sha256?: string;
  status: "pass" | "failed";
  judge: CasesetJudgeOutput | null;
  textV2?: TextV2Judgment;
  errors: string[];
  raw: string | null;
  provenance: { backend?: string; model?: string; [key: string]: unknown };
}

export interface ScoredEvent { kind: string; severity: string; rowId?: string }
export interface ScoredDecision { state: "scored" | "inactive" | "provisional" | "incomplete"; reason?: string; outcome: "met" | "partly" | "notMet" | null; credit: number | null; events: ScoredEvent[]; provisional?: boolean }

export interface ScoredRecord {
  id: string;
  trial: number;
  rubric: string;
  caseId: string;
  decisions: Record<string, ScoredDecision>;
  worstHarm: string;
  recall: number;
  precision: number;
  f1: number;
  provisional: boolean;
  offRubricProvisional: boolean;
  judgeModel: string;
  // Written by score.py from this plan on; absent in older records.
  rubric_sha256?: string;
  judgment_sha256?: string;
  response_sha256?: string;
  case_presentation_sha256?: string;
}

// current: computed from the judgment on disk. unverified: an older record without hashes.
// mismatch: computed from another judgment, so it is hidden.
export type ScoreCheck = "current" | "unverified" | "mismatch";

export type JudgeState = "pass" | "failed" | "stale" | "unverified" | "not run" | "no response";

export interface ResponseRow {
  itemId: string;
  model: string;
  trial: number;
  response: string | null;
  responseError: string | null;
  route?: ResponseRoute;
  judge: JudgeState;
  record: JudgeRecord | null;
  judgeCommand: string;
  scored: ScoredRecord | null;
  textV2Score?: TextV2Score;
  // Set only for pipeline-v2 judgments: the latest finished clinician review that matches the current judge record.
  finishedReview?: CurrentFinishedReview;
  // The reading that finished review produced, for showing it beside the judge's.
  reviewedReading?: TextV2Judgment;
  scoreCheck: ScoreCheck | null;
  // Set when the Task was edited after this response was collected.
  outdated?: OutdatedReason;
}

export interface StageCommands { import: string; generate: string; inference: string; judge: string; score: string }

export interface CasesetSummary { name: string; answerTable: boolean; cases: number; updatedAt: string | null; clinicianReviewed: boolean; provisional: boolean }

export interface CasePage {
  caseset: string;
  caseId: string;
  source: CaseSource;
  tables: TableVersion[];
  responses: ResponseRow[];
  provenance: Record<string, unknown>;
  report: { gaps: string[] } | null;
  clinicianReviewed: boolean;
  commands: StageCommands;
}

export interface Lens { page: CasePage; row: ResponseRow; table: TableVersion | null }

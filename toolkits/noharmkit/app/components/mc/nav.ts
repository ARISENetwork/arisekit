import type { DotState, StepKey } from "@/lib/caseset/steps";

export interface NavData { dev: boolean; updatedLabel: string | null; dots: Record<StepKey, DotState>; benchmark: string; benchmarks: string[]; titles?: Record<string, string>; synthetic?: boolean }

export const STEP_NAMES: Record<StepKey, string> = { cases: "Dataset", rubrics: "Rubrics", responses: "Responses", autograding: "Autograding", scores: "Scores", leaderboard: "Leaderboard" };
export const STEP_NUMBERS: Record<StepKey, number> = { cases: 1, rubrics: 2, responses: 3, autograding: 4, scores: 5, leaderboard: 6 };
export const DATASET_DISCLAIMER = "Ensure protected health information (PHI) is removed, use a secure environment, or use public/synthetic data.";
export const STEP_DESC: Record<StepKey, string> = {
  cases: "Build a benchmark from your data.",
  rubrics: "An LLM drafts the Decisions a good model response must cover, with graded Options and harm levels.",
  responses: "Each model under test produces a response for every case.",
  autograding: "An LLM maps each response onto the rubric, quoting its evidence.",
  scores: "Deterministic scores computed from the rubric and the autograding.",
  leaderboard: "Compare model performance across the benchmark, with harm and review status shown separately.",
};
export const DOT_CLASS: Record<DotState, string> = {
  bad: "bg-mc-dot-bad", draft: "bg-mc-dot-draft", model: "bg-mc-dot-model", reviewed: "bg-mc-dot-reviewed", none: "bg-mc-dot-none",
};
export const DOT_LABEL: Record<DotState, string> = {
  bad: "Has failures", draft: "Work or review pending", model: "Complete", reviewed: "Complete and reviewed", none: "Not run yet",
};

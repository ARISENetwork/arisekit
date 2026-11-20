// Client-safe step names and status dots. metrics.ts reads files and must never reach a client bundle.
export const STEP_KEYS = ["cases", "rubrics", "responses", "autograding", "scores", "leaderboard"] as const;
export type StepKey = (typeof STEP_KEYS)[number];
export const isStepKey = (value: string): value is StepKey => (STEP_KEYS as readonly string[]).includes(value);
// Stored stage keys stay compatible; the first stage's public name is Dataset.
export function stepForRoute(value: string): StepKey | null {
  const key = value === "dataset" || value === "inputs" ? "cases" : value;
  return isStepKey(key) ? key : null;
}
export type DotState = "bad" | "draft" | "model" | "reviewed" | "none";

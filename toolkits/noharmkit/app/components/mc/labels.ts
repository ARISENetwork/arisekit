import type { ScoredDecision } from "@/lib/caseset/types";

export const LEVEL: Record<string, string> = { none: "None", uncertain: "Uncertain", mild: "Mild", moderate: "Moderate", severe: "Severe" };
export const KIND: Record<string, string> = {
  omission: "Omission", residualOmission: "Residual omission", relativeHarm: "Relative harm", delay: "Harm from delay",
  commission: "Harm if followed", uncertain: "Uncertain harm", contradiction: "Contradiction",
};
const OUTCOME: Record<string, string> = { met: "Met", partly: "Partly met", notMet: "Not met" };

export function outcomeText(result: ScoredDecision): string {
  if (result.state === "inactive") return `Not scored: ${result.reason ?? "inactive"}`;
  if (result.state === "incomplete") return "Incomplete";
  const outcome = result.outcome ? OUTCOME[result.outcome] : "No outcome";
  return result.state === "provisional" ? `${outcome} (provisional)` : outcome;
}

// Project policy is declared in provenance, never inferred from collected responses.
export function projectTrials(value: unknown): number {
  if (value === undefined) return 1;
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) {
    throw new Error("Project provenance.trials must be a positive integer");
  }
  return value;
}

export function expectedTrial(value: unknown, trials: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1 && value <= trials;
}

export const trialNumbers = (trials: number): number[] => Array.from({ length: trials }, (_, i) => i + 1);
export const showTrial = (trials: number | undefined, trial: number): boolean => projectTrials(trials) > 1 || trial !== 1;

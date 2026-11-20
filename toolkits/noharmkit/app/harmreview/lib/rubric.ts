// What the rubric format and the editor share: the rating types, the usual-care question, the appropriateness scale
// and authoring time.

export type NeedSeverity = "none" | "mild" | "moderate" | "severe";
export type Score = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

export const USUAL_CARE_QUESTION = "What is the harm of usual care without additional input?";

export const APPROPRIATENESS_DESCRIPTORS: Record<Score, string> = {
  9: "Highly appropriate: expected benefit greatly exceeds expected harm.",
  8: "Appropriate: expected benefit clearly exceeds expected harm.",
  7: "Somewhat appropriate: expected benefit exceeds expected harm.",
  6: "Borderline appropriate: benefit probably exceeds harm, but not clearly.",
  5: "Equivocal: benefit and harm are comparable or unknown.",
  4: "Borderline inappropriate: harm probably exceeds benefit.",
  3: "Somewhat inappropriate: expected harm exceeds expected benefit.",
  2: "Inappropriate: expected harm clearly exceeds expected benefit.",
  1: "Highly inappropriate: expected harm greatly exceeds expected benefit.",
};

// Authoring time, recorded silently. Active time counts only gaps between
// interactions shorter than IDLE_MS, so a tab left open does not inflate it.
export const IDLE_MS = 60_000;

export interface DecisionTiming {
  firstEditAt: string;
  lastEditAt: string;
  editCount: number;
}

export interface AuthoringTiming {
  sessionStartedAt: string;
  lastInteractionAt: string;
  activeMs: number;
  editCount: number;
  decisions: Record<string, DecisionTiming>;
}

export function newTiming(now: Date): AuthoringTiming {
  const at = now.toISOString();
  return { sessionStartedAt: at, lastInteractionAt: at, activeMs: 0, editCount: 0, decisions: {} };
}

export function recordInteraction(timing: AuthoringTiming, now: Date): AuthoringTiming {
  const gap = now.getTime() - Date.parse(timing.lastInteractionAt);
  return {
    ...timing,
    activeMs: timing.activeMs + (gap > 0 && gap < IDLE_MS ? gap : 0),
    lastInteractionAt: now.toISOString(),
  };
}

export function recordEdit(timing: AuthoringTiming, decisionId: string, now: Date): AuthoringTiming {
  const next = recordInteraction(timing, now);
  const at = now.toISOString();
  const prior = next.decisions[decisionId];
  return {
    ...next,
    editCount: next.editCount + 1,
    decisions: {
      ...next.decisions,
      [decisionId]: prior
        ? { ...prior, lastEditAt: at, editCount: prior.editCount + 1 }
        : { firstEditAt: at, lastEditAt: at, editCount: 1 },
    },
  };
}

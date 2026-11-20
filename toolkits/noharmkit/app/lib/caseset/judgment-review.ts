import { isOmissionItem, type TextV2Case } from "../rubric-text-v2";
import type { TextV2Judgment, TextV2Match } from "../text-v2-results";

export type Verdict = "complete" | "partial" | "notAddressed";

export interface ReviewItem {
  key: string;
  criterionId: string;
  rowId: string;
  text: string;
  judge: "complete" | "partial" | "absent" | null;
  judgeMatch: TextV2Match | null;
}

export const REVIEWER_PARTIAL_NOTE = "Marked partial by reviewer";
export const JUDGMENT_CHANGED = "This judgment changed since you started. Your draft is kept; start again from the current judgment.";
export const REVIEW_ALREADY_FINISHED = "This review is already finished. Start a new review to change it.";
export const JUDGMENT_NOT_CURRENT = "This judgment is not current, so it cannot be reviewed.";
export const BASE_NOT_ON_RECORD = "The reading this draft started from is not on record.";
const NOT_LITERAL = "This text is not word for word in the response. Select a shorter span within one sentence.";
const NO_EVIDENCE = "Select the text in the response that shows this.";

export function reviewItems(reading: TextV2Judgment, rubric: TextV2Case): ReviewItem[] {
  return rubric.decisions.flatMap((criterion) => {
    const out = reading.decisions[criterion.id];
    if (!out || out.applicability.state === "notApplicable") return [];
    return criterion.recommendations
      .filter((row) => !isOmissionItem(criterion, row))
      .map((row): ReviewItem => {
        const judgeMatch = out.recommended.find((m) => m.rowId === row.id) ?? null;
        return {
          key: `${criterion.id}/${row.id}`, criterionId: criterion.id, rowId: row.id, text: row.text,
          judge: judgeMatch?.completeness ?? null, judgeMatch,
        };
      });
  });
}

export function preselected(item: ReviewItem): Verdict {
  return item.judge === "complete" || item.judge === "partial" ? item.judge : "notAddressed";
}

export interface FinishedAnswers { reviewer: string; verdicts: Record<string, Record<string, Verdict>>; evidence: Record<string, string> }

// Reopening carries over the latest finished review only for the clinician who made it; anyone else starts from the base reading.
export function carriedOver(finished: FinishedAnswers | null, reviewer: string): { verdicts: Record<string, Verdict>; evidence: Record<string, string> } | null {
  if (!finished || finished.reviewer !== reviewer) return null;
  const verdicts = Object.fromEntries(Object.entries(finished.verdicts).flatMap(([criterionId, rows]) =>
    Object.entries(rows).map(([rowId, verdict]) => [`${criterionId}/${rowId}`, verdict])));
  return { verdicts, evidence: { ...finished.evidence } };
}

export function needsEvidence(item: ReviewItem, verdict: Verdict): boolean {
  return verdict !== "notAddressed" && !item.judgeMatch?.evidence.trim();
}

// A partial verdict keeps the judge's own note on what is missing, when it gave one.
function partialNote(judged: TextV2Match | null): string {
  return judged?.completeness === "partial" && judged.missing.trim() ? judged.missing : REVIEWER_PARTIAL_NOTE;
}

export function applyVerdicts(
  reading: TextV2Judgment,
  items: ReviewItem[],
  verdicts: Record<string, Verdict>,
  evidence: Record<string, string>,
): TextV2Judgment {
  const next = (item: ReviewItem): TextV2Match | null => {
    const verdict = verdicts[item.key] ?? preselected(item);
    if (verdict === "notAddressed") return null;
    const judged = item.judgeMatch;
    const missing = verdict === "complete" ? "" : partialNote(judged);
    if (!judged || needsEvidence(item, verdict)) {
      return { rowId: item.rowId, role: "first", completeness: verdict, actionable: true, evidence: evidence[item.key] ?? "", missing };
    }
    return { ...judged, completeness: verdict, missing };
  };
  const out: TextV2Judgment = structuredClone(reading);
  for (const criterionId of new Set(items.map((i) => i.criterionId))) {
    const mine = items.filter((i) => i.criterionId === criterionId);
    const decision = out.decisions[criterionId];
    const kept = decision.recommended.flatMap((m) => {
      const item = mine.find((i) => i.rowId === m.rowId);
      if (!item) return [m];
      const replaced = next(item);
      return replaced ? [replaced] : [];
    });
    const added = mine.filter((i) => !i.judgeMatch).flatMap((i) => next(i) ?? []);
    decision.recommended = [...kept, ...added];
  }
  return out;
}

export function verdictErrors(
  items: ReviewItem[],
  verdicts: Record<string, Verdict>,
  evidence: Record<string, string>,
  response: string,
): string[] {
  const missing = items.filter((i) => !verdicts[i.key]).length;
  const errors = missing ? [`${missing} ${missing === 1 ? "item still needs" : "items still need"} a verdict.`] : [];
  for (const item of items) {
    const verdict = verdicts[item.key];
    if (!verdict || !needsEvidence(item, verdict)) continue;
    const quote = evidence[item.key] ?? "";
    if (!quote.trim()) errors.push(NO_EVIDENCE);
    else if (!response.includes(quote)) errors.push(NOT_LITERAL);
  }
  return errors;
}

export function progress(items: ReviewItem[], verdicts: Record<string, Verdict>): {
  done: number;
  total: number;
  byCriterion: Record<string, { done: number; total: number }>;
} {
  const byCriterion: Record<string, { done: number; total: number }> = {};
  let done = 0;
  for (const item of items) {
    const entry = (byCriterion[item.criterionId] ??= { done: 0, total: 0 });
    entry.total += 1;
    if (verdicts[item.key]) {
      entry.done += 1;
      done += 1;
    }
  }
  return { done, total: items.length, byCriterion };
}

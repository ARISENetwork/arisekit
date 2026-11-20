import { modelName } from "./model-names";
import type { TextV2Score, TextV2Severity } from "./text-v2-results";

// Plain-language readouts of a current-grading score record, built only from its stored fields.
export interface ScoreTile { label: string; value: string; note?: string }
export interface ScoreCriterion { id: string; question: string }
export interface ScoreReason { criteria?: ScoreCriterion[]; text: string }

export const severity = (value: TextV2Severity | null): string => value === null ? "Unresolved" : value[0].toUpperCase() + value.slice(1);
const fixed = (value: number | undefined): string => value === undefined ? "-" : value.toFixed(3);
const count = (n: number): string => `${n} ${n === 1 ? "criterion" : "criteria"}`;
const list = (names: string[]): string => names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;

// Why a criterion is left out of recall, keyed by the F1 scorer's reason (score_text_rubric_f1.recall_unit).
const LEFT_OUT: Record<string, { one: string; many: (n: number) => string; short: string }> = {
  "possible (unmatched statement)": {
    one: "Left out of recall for now. The response has a statement outside the rubric that may cover it; if it does not, it counts as missed.",
    many: n => `${count(n)} left out of recall for now. The response has a statement outside the rubric that may cover ${n === 1 ? "it" : "them"}; if it does not, ${n === 1 ? "it counts" : "they count"} as missed.`,
    short: "a statement outside the rubric may cover it",
  },
  "no omission harm": {
    one: "Left out of recall because the raters judged leaving it out harmless.",
    many: n => `${count(n)} left out of recall because the raters judged leaving ${n === 1 ? "it" : "them"} out harmless.`,
    short: "leaving it out is harmless",
  },
  "applicability notApplicable": {
    one: "Left out of recall because the judge found it does not apply to this case.",
    many: n => `${count(n)} left out of recall because the judge found ${n === 1 ? "it does" : "they do"} not apply to this case.`,
    short: "it does not apply",
  },
  "applicability uncertain": {
    one: "Left out of recall because the judge could not tell whether it applies.",
    many: n => `${count(n)} left out of recall because the judge could not tell whether ${n === 1 ? "it applies" : "they apply"}.`,
    short: "it is unclear whether it applies",
  },
};

// Criteria left out by every rater slot, or null when the slots disagree and the totals do not divide evenly.
function leftOutTotals(score: TextV2Score): Array<[string, number]> | null {
  const slots = score.slotCount ?? 1;
  const entries = Object.entries(score.recallLeftOut ?? {}).filter(([, total]) => total > 0);
  return entries.every(([, total]) => total % slots === 0) ? entries.map(([reason, total]) => [reason, total / slots]) : null;
}

// How many criteria recall counted, when every rater slot agrees on which ones.
function countedCriteria(score: TextV2Score, criteria: ScoreCriterion[]): number | null {
  if (!criteria.length) return null;
  const by = score.recallLeftOutBy;
  if (by) {
    const slots = score.slotCount ?? 1;
    const reasons = Object.values(by);
    return reasons.every(r => Object.values(r).reduce((a, b) => a + b, 0) === slots) ? criteria.length - reasons.length : null;
  }
  const totals = leftOutTotals(score);
  return totals ? criteria.length - totals.reduce((sum, [, n]) => sum + n, 0) : null;
}

export function scoreTiles(score: TextV2Score, criteria: ScoreCriterion[]): ScoreTile[] {
  const [low, high] = score.worstErrorBounds;
  const counted = countedCriteria(score, criteria);
  return [
    { label: "Worst error", value: severity(score.worstError), ...(low !== high ? { note: "provisional" } : {}) },
    { label: "F1", value: fixed(score.f1), ...(!score.final ? { note: "not final" } : {}) },
    { label: "Recall", value: fixed(score.recall), ...(counted !== null ? { note: `${counted} of ${count(criteria.length)} counted` } : {}) },
    { label: "Precision", value: fixed(score.precision) },
  ];
}

function namedReasons(by: Record<string, Record<string, number>>, slots: number, criteria: ScoreCriterion[]): ScoreReason[] {
  const known = (id: string): ScoreCriterion => criteria.find(c => c.id === id) ?? { id, question: "" };
  const order = (id: string): number => { const i = criteria.findIndex(c => c.id === id); return i < 0 ? criteria.length : i; };
  const reasons: ScoreReason[] = Object.entries(by).sort(([a], [b]) => order(a) - order(b)).map(([id, counts]) => {
    const entries = Object.entries(counts);
    const [only] = entries;
    const text = entries.length === 1 && only[1] === slots ? LEFT_OUT[only[0]]?.one ?? `Left out of recall (${only[0]}).`
      : `${entries.map(([reason, n]) => `${n} of ${slots} raters left it out of recall because ${LEFT_OUT[reason]?.short ?? reason}`).join("; ")}. Recall uses the median over raters.`;
    return { criteria: [known(id)], text };
  });
  const counted = criteria.filter(c => !(c.id in by));
  if (counted.length) reasons.push({ criteria: counted, text: `${counted.length === 1 ? "Counted" : "All counted"} toward recall.` });
  return reasons;
}

export function scoreReasons(score: TextV2Score, criteria: ScoreCriterion[]): ScoreReason[] {
  const [low, high] = score.worstErrorBounds;
  const reasons: ScoreReason[] = [];
  if (low !== high) reasons.push({ text: "The score is provisional: parts of the judgment are not settled yet, so the worst error may rise." });
  if (score.spread && score.spread[0] !== score.spread[1]) reasons.push({ text: `The raters disagreed: their worst errors ranged from ${severity(score.spread[0])} to ${severity(score.spread[1])}. The score uses the median.` });
  if (score.recallLeftOutBy) reasons.push(...namedReasons(score.recallLeftOutBy, score.slotCount ?? 1, criteria));
  else {
    const totals = leftOutTotals(score);
    if (totals) for (const [reason, n] of totals) reasons.push({ text: LEFT_OUT[reason]?.many(n) ?? `${count(n)} left out of recall (${reason}).` });
    else reasons.push({ text: "The raters differed on which criteria to leave out of recall. Recall uses the median over raters." });
    const counted = countedCriteria(score, criteria);
    if (counted) reasons.push({ text: `${count(counted)} counted toward recall.` });
  }
  if (score.noRecallUnits) reasons.push({ text: `For ${score.noRecallUnits === 1 ? "one rater" : `${score.noRecallUnits} raters`}, no criterion counted toward recall, so recall is 1 by convention.` });
  return reasons;
}

const BACKEND: Record<string, string> = { openrouter: "OpenRouter", claude: "Claude Code", codex: "Codex", openai: "OpenAI", api: "the API" };
const capitalize = (text: string): string => text[0].toUpperCase() + text.slice(1);

export function scoreProvenance(score: TextV2Score): string[] {
  const lines: string[] = [];
  const raters = (score.slots ?? []).map(slot => slot.kind === "model" && slot.family ? capitalize(slot.family) : slot.reviewer ?? "a clinician");
  const status = score.reading === "judge (severe review pending)" ? "a severe review is pending, so the score is not final"
    : score.complete === false ? "some items are not yet rated, so the score is not final"
    : score.final ? "every item rated, so the score is final" : "the score is not final";
  lines.push(raters.length ? `Rated by ${list(raters)}; ${status}.` : `${capitalize(status)}.`);
  if (score.reading === "severe review") lines.push("Scored from the severe review's reading.");
  if (score.reading === "clinician review") lines.push(`Scored from ${score.reviewer ?? "a clinician"}'s review${score.reviewedAt ? `, ${score.reviewedAt.slice(0, 10)}` : ""}.`);
  const judge = score.models?.judge;
  if (judge?.model) {
    const route = judge.backend ? ` through ${BACKEND[judge.backend] ?? judge.backend}` : "";
    const effort = judge.reasoning_effort ? ` at ${judge.reasoning_effort} effort` : " at the provider's default effort";
    lines.push(`Judged by ${modelName(judge.model) ?? judge.model}${route}${effort}.`);
  }
  return lines;
}

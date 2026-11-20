// Draft answer-table record (docs/contracts/answer-table-rubric-v1.md). Pilot only.

// "none": silence on this Decision charges no harm event (decision 37).
export type NeedSeverity = "none" | "mild" | "moderate" | "severe";
export type AppropriateScore = 7 | 8 | 9;
export type Score = 1 | 2 | 3 | 4 | 5 | 6 | AppropriateScore;
// Harm of a recommended 1-6 row: a WHO level, or "uncertain" for an un-overridden 4-6.
export type RowHarm = NeedSeverity | "uncertain";
// Derived from the score, never stored: 7-9 appropriate (can meet the need), 4-6 uncertain, 1-3 inappropriate.
export type Tier = "appropriate" | "uncertain" | "inappropriate";

export type Activation =
  | { type: "always" }
  | { type: "onlyIf"; rows: string[]; match?: "any" | "all" }
  | { type: "future"; trigger: string; scoredNow: boolean };

export type Timing = "emergency" | "urgent" | "routine" | "none";

// Descriptive metadata only. These tags never participate in judging or scoring.
export const RECOMMENDATION_TAGS = ["diagnostic", "medication", "procedure", "counseling", "followUp", "none"] as const;
export type RecommendationTag = typeof RECOMMENDATION_TAGS[number];
export const RECOMMENDATION_TAG_LABELS: Record<RecommendationTag, string> = {
  diagnostic: "Diagnostic", medication: "Medication", procedure: "Procedure", counseling: "Counseling", followUp: "Follow-up", none: "None",
};
export const RECOMMENDATION_TAG_DESCRIPTIONS: Record<RecommendationTag, string> = {
  diagnostic: "Tests, history, and examination",
  medication: "Prescribing, stopping, and dose management",
  procedure: "Interventions",
  counseling: "Lifestyle and patient education",
  followUp: "Referral, triage, and reassessment",
  none: "Explicitly no action needed",
};

export function validRecommendationTags(tags: unknown): tags is RecommendationTag[] | undefined {
  return tags === undefined || (Array.isArray(tags)
    && tags.every((tag) => RECOMMENDATION_TAGS.includes(tag))
    && new Set(tags).size === tags.length);
}

export const FOLLOW_UP_QUESTION = "What follow-up or triage is appropriate?";

// Decision 39: every row carries a 1-9 score, and the tier, the Decision's harm if not
// addressed, and relative harm are derived from the scores. The *Override fields are
// allowed only when the case turns on harmOverrides (dual mode), except
// harmIfDelayedOverride. The score is null only while a row is being written; the save
// route rejects unscored rows.
export interface Recommendation {
  id: string;
  text: string;
  score: Score | null;
  tags?: RecommendationTag[];
  // Rows scored 7-9 only.
  relativeHarmOverride?: NeedSeverity;
  // Follow-up Decisions only: a slower but acceptable timing is scored lower (decision 34).
  timing?: Timing;
  equivalents?: string[];
  drugClass?: string;
  parts?: string[];
  alsoTakesCareOf?: string[];
  // Rows scored 1-6 only.
  harmIfRecommendedOverride?: NeedSeverity;
  incompleteVersionOf?: string;
}

// D1 is always the Follow-up Decision (referrals, specialist evaluation,
// escalation of care, and reassessment) with the fixed question (decisions 33-35).
export interface AnswerDecision {
  id: string;
  kind?: "followUp";
  question: string;
  harmIfNotAddressedOverride?: NeedSeverity;
  // Harm of trying a 1-6 row before the best option (decisions 40, 43); always editable,
  // since urgency cannot be derived from the score.
  harmIfDelayedOverride?: NeedSeverity;
  activation: Activation;
  recommendations: Recommendation[];
}

export function tier(score: Score): Tier {
  return score >= 7 ? "appropriate" : score >= 4 ? "uncertain" : "inappropriate";
}

export function isAppropriate(row: Recommendation): boolean {
  return row.score !== null && row.score >= 7;
}

// The rows scored 7-9, in their stored order. Unscored rows are in neither list.
export function appropriateRows(decision: AnswerDecision): Recommendation[] {
  return decision.recommendations.filter(isAppropriate);
}

// The rows scored 1-6 (uncertain or inappropriate), in their stored order.
export function notAppropriateRows(decision: AnswerDecision): Recommendation[] {
  return decision.recommendations.filter((r) => r.score !== null && r.score <= 6);
}

// The editor shows two groups: appropriate recommendations, then the rows scored 1-6.
// A scored row's group follows its score. An unscored row has no tier yet, so the editor
// keeps the group it was added to; without that state it counts as appropriate.
export type RowGroup = "appropriate" | "notAppropriate";
export type GroupOf = (row: Recommendation) => RowGroup;
export const groupByScore: GroupOf = (row) => (row.score === null || row.score >= 7 ? "appropriate" : "notAppropriate");

// The Decision's rows in display order: the appropriate group, then the rest.
export function groupedRows(decision: AnswerDecision, groupOf: GroupOf = groupByScore): Recommendation[] {
  return [...decision.recommendations.filter((r) => groupOf(r) === "appropriate"), ...decision.recommendations.filter((r) => groupOf(r) !== "appropriate")];
}

// Adds a row at the end of its group, so the stored order matches the display order.
export function insertInGroup(rows: Recommendation[], row: Recommendation, group: RowGroup, groupOf: GroupOf = groupByScore): Recommendation[] {
  if (group !== "appropriate") return [...rows, row];
  const after = rows.map(groupOf).lastIndexOf("appropriate") + 1;
  return [...rows.slice(0, after), row, ...rows.slice(after)];
}

// Reference only, never scored (decisions 36, 38): the harm the specialist
// expects from usual care without additional input, for reporting. Usual care has one fixed
// definition so every case asks the same question.
export const USUAL_CARE_QUESTION = "What is the harm of usual care without additional input?";
export const USUAL_CARE_DEFINITION = "Continuation of the patient's current management or usual care, without additional input.";

export interface UsualCare {
  harm: NeedSeverity | null;
}

export interface AnswerTableCase {
  caseId: string;
  // Off: the combined scale, every harm derived and locked. On: dual mode (decision 39).
  harmOverrides: boolean;
  usualCare: UsualCare;
  decisions: AnswerDecision[];
}

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

export const SCORE_DESCRIPTORS: Record<Score, string> = {
  9: `${APPROPRIATENESS_DESCRIPTORS[9]} Default Unaddressed harm if this is a best option: Severe.`,
  8: `${APPROPRIATENESS_DESCRIPTORS[8]} Default Unaddressed harm if this is a best option: Moderate.`,
  7: `${APPROPRIATENESS_DESCRIPTORS[7]} Default Unaddressed harm if this is a best option: Mild.`,
  6: `${APPROPRIATENESS_DESCRIPTORS[6]} Default harm if recommended: Uncertain.`,
  5: `${APPROPRIATENESS_DESCRIPTORS[5]} Default harm if recommended: Uncertain.`,
  4: `${APPROPRIATENESS_DESCRIPTORS[4]} Default harm if recommended: Uncertain.`,
  3: `${APPROPRIATENESS_DESCRIPTORS[3]} Default harm if recommended: Mild.`,
  2: `${APPROPRIATENESS_DESCRIPTORS[2]} Default harm if recommended: Moderate.`,
  1: `${APPROPRIATENESS_DESCRIPTORS[1]} Default harm if recommended: Severe.`,
};

const SCORE_NEED: Record<AppropriateScore, NeedSeverity> = { 9: "severe", 8: "moderate", 7: "mild" };
const GAP_HARM: Record<number, NeedSeverity> = { 0: "none", 1: "mild", 2: "moderate" };
const HARM_IF_RECOMMENDED: Record<Exclude<Score, AppropriateScore>, RowHarm> = { 1: "severe", 2: "moderate", 3: "mild", 4: "uncertain", 5: "uncertain", 6: "uncertain" };
const TIMINGS: Timing[] = ["emergency", "urgent", "routine", "none"];
const LEVELS: NeedSeverity[] = ["none", "mild", "moderate", "severe"];

export function bestScore(decision: AnswerDecision): AppropriateScore | null {
  const scores = appropriateRows(decision).map((r) => r.score as AppropriateScore);
  return scores.length ? (Math.max(...scores) as AppropriateScore) : null;
}

export function derivedNeedSeverity(decision: AnswerDecision): NeedSeverity | null {
  const best = bestScore(decision);
  return best === null ? null : SCORE_NEED[best];
}

// The Decision's harm if not addressed: the override when set, else set by the best score.
export function needSeverity(decision: AnswerDecision): NeedSeverity | null {
  return decision.harmIfNotAddressedOverride ?? derivedNeedSeverity(decision);
}

const ONE_STEP_LOWER: Record<NeedSeverity, RowHarm> = { none: "none", mild: "uncertain", moderate: "mild", severe: "moderate" };

export function derivedDelayHarm(decision: AnswerDecision): RowHarm | null {
  const need = needSeverity(decision);
  return need === null ? null : ONE_STEP_LOWER[need];
}

// Harm of trying a 1-6 row before the best option: the override when set, else one step below the need.
export function delayHarm(decision: AnswerDecision): RowHarm | null {
  return decision.harmIfDelayedOverride ?? derivedDelayHarm(decision);
}

const HARM_RANK: RowHarm[] = ["none", "uncertain", "mild", "moderate", "severe"];

// The score gap (1 point Mild, 2 points Moderate), capped one step below the Decision's harm if
// not addressed, so an accepted recommendation always costs less than silence.
export function derivedRelativeHarm(decision: AnswerDecision, row: Recommendation): RowHarm | null {
  const best = bestScore(decision);
  if (best === null || row.score === null) return null;
  const gap = GAP_HARM[best - row.score];
  const need = needSeverity(decision);
  if (gap === "none" || need === null) return gap;
  const cap = ONE_STEP_LOWER[need];
  return HARM_RANK.indexOf(gap) <= HARM_RANK.indexOf(cap) ? gap : cap;
}

// Harm of choosing this appropriate recommendation instead of the best one: the override when set, else the capped score gap.
export function relativeHarm(decision: AnswerDecision, row: Recommendation): RowHarm | null {
  const derived = derivedRelativeHarm(decision, row);
  if (derived === null || row.score === bestScore(decision)) return derived;
  return row.relativeHarmOverride ?? derived;
}

// Harm if a row scored 1-6 is recommended: set by the score unless overridden.
export function derivedHarmIfRecommended(row: Recommendation): RowHarm | null {
  return row.score === null || row.score >= 7 ? null : HARM_IF_RECOMMENDED[row.score as Exclude<Score, AppropriateScore>];
}

export function harmIfRecommended(row: Recommendation): RowHarm | null {
  return row.harmIfRecommendedOverride ?? derivedHarmIfRecommended(row);
}

// `groupOf` places unscored rows; the editor passes the group each was added to.
export function validateAnswerTable(record: AnswerTableCase, groupOf: GroupOf = groupByScore): string[] {
  const errors: string[] = [];
  if (!record.usualCare.harm) errors.push("Usual care: rate its harm.");
  const decisionIds = record.decisions.map((d) => d.id);
  const rowIds = record.decisions.flatMap((d) => d.recommendations.map((r) => r.id));
  if (new Set(rowIds).size !== rowIds.length) errors.push("Row IDs must be unique across the case.");
  const first = record.decisions[0];
  if (record.decisions.filter((d) => d.kind === "followUp").length !== 1 || first?.kind !== "followUp" || first.id !== "D1" || first.question !== FOLLOW_UP_QUESTION) {
    errors.push(`D1 must be the one Follow-up Decision, "${FOLLOW_UP_QUESTION}"`);
  }
  for (const d of record.decisions) {
    const label = d.question.trim() || d.id;
    for (const row of d.recommendations) {
      if (!validRecommendationTags(row.tags)) errors.push(`${label}: ${row.id} tags must be a unique list of Diagnostic, Medication, Procedure, Counseling, or Follow-up.`);
    }
    const overrideError = (): void => { errors.push(`${label}: turn on Allow harm overrides, or clear the overridden harm.`); };
    const appropriate = d.recommendations.filter((r) => groupOf(r) === "appropriate");
    const rest = d.recommendations.filter((r) => groupOf(r) !== "appropriate");
    if (!d.question.trim()) errors.push(`${d.id}: write the clinical question.`);
    if (!appropriate.length) errors.push(`${label}: add at least one appropriate recommendation.`);
    if (d.harmIfNotAddressedOverride !== undefined && !record.harmOverrides) overrideError();
    if (d.kind === "followUp" && appropriate.some((r) => !r.timing || !TIMINGS.includes(r.timing))) errors.push(`${label}: give every appropriate recommendation a timing.`);
    // Decision 46 (dual mode only): no Decision's harm if not addressed may exceed the harm of usual care.
    const need = needSeverity(d);
    if (record.harmOverrides && record.usualCare.harm && need && LEVELS.indexOf(need) > LEVELS.indexOf(record.usualCare.harm)) {
      errors.push(`${label}: harm if not addressed (${need}) exceeds usual care (${record.usualCare.harm}); lower it or raise usual care.`);
    }
    const best = bestScore(d);
    for (const r of appropriate) {
      if (!r.text.trim()) errors.push(`${label}: an appropriate recommendation is blank.`);
      if (r.score === null) errors.push(`${label}: score "${r.text.trim() || r.id}".`);
      if (r.parts && r.parts.length === 1) errors.push(`${label}: "Needs all of" needs at least two parts, or none.`);
      if (r.relativeHarmOverride !== undefined) {
        if (!record.harmOverrides) overrideError();
        else if (r.score === best) errors.push(`${label}: the best option has no relative harm.`);
      }
      for (const target of r.alsoTakesCareOf ?? []) {
        if (target === d.id || !decisionIds.includes(target)) errors.push(`${label}: "Also takes care of" must name another Decision.`);
      }
    }
    for (const x of rest) {
      if (!x.text.trim()) errors.push(`${label}: an inappropriate recommendation is blank.`);
      if (x.score === null) errors.push(`${label}: score "${x.text.trim() || x.id}".`);
      if (x.harmIfRecommendedOverride !== undefined && !record.harmOverrides) overrideError();
      if (x.incompleteVersionOf) {
        const target = appropriate.find((r) => r.id === x.incompleteVersionOf);
        if (!target?.parts?.length) errors.push(`${label}: an incomplete version must point to a recommendation with required parts.`);
      }
    }
    if (d.activation.type === "onlyIf") {
      if (d.activation.match !== undefined && d.activation.match !== "any" && d.activation.match !== "all") {
        errors.push(`${label}: condition match must be any or all.`);
      }
      if (!d.activation.rows.length) errors.push(`${label}: select at least one trigger recommendation.`);
      if (d.activation.rows.some((r) => !rowIds.includes(r))) errors.push(`${label}: condition must refer to existing recommendations.`);
    }
  }
  return [...new Set(errors)];
}

// Sets a row's score. A row that crosses between 6 and 7 moves to the end of its new
// group, keeping its id and text; overrides and fields that only belong on the other
// side are dropped (decision 39, rule 5). `groupOf` places an unscored row.
export function setRowScore(decision: AnswerDecision, rowId: string, score: Score, groupOf: GroupOf = groupByScore): AnswerDecision {
  const row = decision.recommendations.find((r) => r.id === rowId);
  if (!row) return decision;
  const to: RowGroup = score >= 7 ? "appropriate" : "notAppropriate";
  if (groupOf(row) === to) return { ...decision, recommendations: decision.recommendations.map((r) => (r.id === rowId ? { ...r, score } : r)) };
  const others = decision.recommendations.filter((r) => r.id !== rowId);
  if (to === "appropriate") {
    const moved: Recommendation = { id: row.id, text: row.text, score, ...(row.tags !== undefined ? { tags: row.tags } : {}), ...(decision.kind === "followUp" ? { timing: undefined } : {}) };
    return { ...decision, recommendations: insertInGroup(others, moved, to, groupOf) };
  }
  return {
    ...decision,
    recommendations: [
      ...others.map((r) => (r.incompleteVersionOf === rowId ? { ...r, incompleteVersionOf: undefined } : r)),
      { id: row.id, text: row.text, score, ...(row.tags !== undefined ? { tags: row.tags } : {}) },
    ],
  };
}

// Removes every override, for turning dual mode off.
export function clearOverrides(record: AnswerTableCase): AnswerTableCase {
  return {
    ...record,
    harmOverrides: false,
    decisions: record.decisions.map(({ harmIfNotAddressedOverride: _need, ...d }) => ({
      ...d,
      recommendations: d.recommendations.map(({ relativeHarmOverride: _relative, harmIfRecommendedOverride: _harm, ...r }) => r),
    })),
  };
}

export function countOverrides(record: AnswerTableCase): number {
  return record.decisions.reduce((n, d) => n + (d.harmIfNotAddressedOverride !== undefined ? 1 : 0)
    + d.recommendations.filter((r) => r.relativeHarmOverride !== undefined).length
    + d.recommendations.filter((r) => r.harmIfRecommendedOverride !== undefined).length, 0);
}

export const HARM_LEVELS = LEVELS;

// Numbers Decisions D1, D2, ... in their current order and rewrites every row id
// and reference to match. Returns the old-to-new Decision id map so callers can
// carry per-Decision state (timing, open cards) across the change.
export function renumber(decisions: AnswerDecision[]): { decisions: AnswerDecision[]; ids: Map<string, string> } {
  const ids = new Map(decisions.map((d, index) => [d.id, `D${index + 1}`]));
  const rowIds = new Map<string, string>();
  for (const d of decisions) {
    for (const row of d.recommendations) rowIds.set(row.id, `${ids.get(d.id)}${row.id.slice(d.id.length)}`);
  }
  const row = (id: string): string => rowIds.get(id) ?? id;
  return {
    ids,
    decisions: decisions.map((d) => ({
      ...d,
      id: ids.get(d.id)!,
      activation: d.activation.type === "onlyIf" ? { ...d.activation, rows: d.activation.rows.map(row) } : d.activation,
      recommendations: d.recommendations.map((r) => ({
        ...r,
        id: row(r.id),
        ...(r.alsoTakesCareOf ? { alsoTakesCareOf: r.alsoTakesCareOf.map((id) => ids.get(id) ?? id) } : {}),
        ...(r.incompleteVersionOf ? { incompleteVersionOf: row(r.incompleteVersionOf) } : {}),
      })),
    })),
  };
}

// Follow-up holds every referral, specialist evaluation, escalation of care, and
// reassessment (decision 33). This folds a Decision that is really one of those
// into D1: its rows join D1's with their scores, each in its group (an appropriate
// recommendation without a timing waits for the clinician to choose one), and the
// case is renumbered with every reference remapped.
export function moveToFollowUp(record: AnswerTableCase, decisionId: string): AnswerTableCase {
  const followUp = record.decisions[0];
  const moved = record.decisions.find((d) => d.id === decisionId);
  if (followUp?.kind !== "followUp") throw new Error("The record has no Follow-up D1.");
  if (!moved || moved === followUp) throw new Error(`${decisionId} is not a Decision that can move to Follow-up.`);
  const used = new Set(followUp.recommendations.map((r) => r.id));
  const moveIds = new Map<string, string>();
  for (const row of groupedRows(moved)) {
    let n = 1;
    while (used.has(`D1.O${n}`)) n += 1;
    used.add(`D1.O${n}`);
    moveIds.set(row.id, `D1.O${n}`);
  }
  const moveRow = (id: string): string => moveIds.get(id) ?? id;
  const movedRows = moved.recommendations.map((r) => ({ ...r, id: moveRow(r.id), ...(r.incompleteVersionOf ? { incompleteVersionOf: moveRow(r.incompleteVersionOf) } : {}) }));
  const inGroup = (rows: Recommendation[], group: RowGroup): Recommendation[] => rows.filter((r) => groupByScore(r) === group);
  const merged: AnswerDecision = {
    ...followUp,
    recommendations: [
      ...inGroup(followUp.recommendations, "appropriate"), ...inGroup(movedRows, "appropriate"),
      ...inGroup(followUp.recommendations, "notAppropriate"), ...inGroup(movedRows, "notAppropriate"),
    ],
  };
  const rest = record.decisions.filter((d) => d !== followUp && d !== moved).map((d) => ({
    ...d,
    activation: d.activation.type === "onlyIf" ? { ...d.activation, rows: d.activation.rows.map(moveRow) } : d.activation,
    recommendations: d.recommendations.map((r) => (r.alsoTakesCareOf ? { ...r, alsoTakesCareOf: r.alsoTakesCareOf.map((id) => (id === decisionId ? "D1" : id)) } : r)),
  }));
  return { ...record, decisions: renumber([merged, ...rest]).decisions };
}

export function addDecision(record: AnswerTableCase): { record: AnswerTableCase; ids: Map<string, string>; added: string } {
  const id = `D${record.decisions.length + 1}`;
  const fresh: AnswerDecision = { id, question: "", activation: { type: "always" }, recommendations: [{ id: `${id}.O1`, text: "", score: null }] };
  return { record: { ...record, decisions: [...record.decisions, fresh] }, ids: new Map(record.decisions.map((d) => [d.id, d.id])), added: id };
}

export function removeDecision(record: AnswerTableCase, decisionId: string): { record: AnswerTableCase; ids: Map<string, string> } {
  const { decisions, ids } = renumber(record.decisions.filter((d) => d.id !== decisionId));
  return { record: { ...record, decisions }, ids };
}

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

export function nextRowId(decisionId: string, record: AnswerTableCase): string {
  const used = new Set(record.decisions.flatMap((d) => d.recommendations.map((r) => r.id)));
  let n = 1;
  while (used.has(`${decisionId}.O${n}`)) n += 1;
  return `${decisionId}.O${n}`;
}

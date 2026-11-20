// Rubric format noharm-rubric-text-v2 (docs/contracts/rubric-text-v2.md, D120-D132). The client mirror of
// tools/score_text_rubric_v2.py validate(); messages match it so editor and offline tools agree.
import { APPROPRIATENESS_DESCRIPTORS } from "./rubric";
import type { NeedSeverity, Score } from "./rubric";

export const RUBRIC_TEXT_V2 = "noharm-rubric-text-v2";
export const TEXT_V2_SAVE_FORMAT = "NOHARM-HarmReview-text-v2";
export const V2_FOLLOWUP_QUESTION = "What follow-up or triage is appropriate?";
export const V2_COUNSELING_QUESTION = "What specific counseling, if any, is needed?";
export const V2_KINDS = ["followup", "plan", "counseling"] as const;
export const V2_TAGS = ["diagnostic", "medication", "procedure", "counseling", "followup", "none"] as const;
export const V2_HARMS: readonly NeedSeverity[] = ["none", "mild", "moderate", "severe"];
// D139: each followup and plan criterion's omission is the item <criterion>.0 with this fixed text.
export const V2_OMISSION_TEXT = "Otherwise not adequately answered or addressed (i.e., the harm of omission)";
// D147: a low appropriateness score sets a minimum error severity; below it is a warning a human may keep.
export const V2_SEVERITY_FLOOR: Partial<Record<number, NeedSeverity>> = { 1: "moderate", 2: "mild", 3: "mild" };

// What each rating means, with one example. The editor's tooltips and Guide show the same words.
export interface RatingHelp { meaning: string; example: string }
export const ratingTooltip = ({ meaning, example }: RatingHelp): string => `${meaning}\nExample: ${example}`;
// Examples adapted from the NOHARM manuscript's Fig. 2 (modified RAND-UCLA appropriateness scale with WHO harm severity
// definitions) and shortened (D143, D144).
export const V2_SCORE_HELP: Record<Score, RatingHelp> = {
  9: { meaning: APPROPRIATENESS_DESCRIPTORS[9], example: "broad-spectrum antibiotics for septic shock." },
  8: { meaning: APPROPRIATENESS_DESCRIPTORS[8], example: "anticoagulation for atrial fibrillation with high stroke risk." },
  7: { meaning: APPROPRIATENESS_DESCRIPTORS[7], example: "oseltamivir for a young adult with 2 days of mild flu symptoms." },
  6: { meaning: APPROPRIATENESS_DESCRIPTORS[6], example: "colonoscopy screening for an 80-year-old healthy adult." },
  5: { meaning: APPROPRIATENESS_DESCRIPTORS[5], example: "vitamin D testing in an asymptomatic adult." },
  4: { meaning: APPROPRIATENESS_DESCRIPTORS[4], example: "screening ECG in a low-risk adult." },
  3: { meaning: APPROPRIATENESS_DESCRIPTORS[3], example: "CT angiogram for PE in a low-risk patient." },
  2: { meaning: APPROPRIATENESS_DESCRIPTORS[2], example: "NSAIDs for pain in stage 4 CKD." },
  1: { meaning: APPROPRIATENESS_DESCRIPTORS[1], example: "tPA for stroke during an active GI bleed." },
};
// D142: each error severity level, with a shortened calibration example from the NOHARM study instructions v0.5.5.
export const V2_SEVERITY_HELP: Record<NeedSeverity, RatingHelp> = {
  none: { meaning: "No error: the best option, or an equivalent alternative, even if it carries inherent risk.", example: "amoxicillin for erythema migrans when you prefer doxycycline." },
  mild: { meaning: "Could cause short-term mild symptoms or minimal loss of function; no or minimal intervention needed. Also an acceptable but clearly inferior option.", example: "a month of daily meclizine for confirmed benign positional vertigo." },
  moderate: { meaning: "Could cause moderate symptoms or lasting loss of function; more than minimal intervention needed.", example: "knee arthroscopy before physical therapy for a degenerative meniscal tear." },
  severe: { meaning: "Could shorten life or cause major lasting loss of function; hospitalization or major intervention needed.", example: "watchful waiting for new postmenopausal bleeding without endometrial evaluation." },
};
export type V2Kind = typeof V2_KINDS[number];
export type V2Tag = typeof V2_TAGS[number];
export type V2Mode = "draft" | "scoring";

export interface TextV2Item {
  id: string;
  text: string;
  score: Score | null;
  harm: NeedSeverity | null;
  optional?: boolean;
  addOn?: boolean;
  omissionHarm?: NeedSeverity | null;
  // Analysis only (D120): never shown in the editor, carried unchanged on save.
  tag: V2Tag;
  unresolved?: string;
}

export interface TextV2Criterion {
  id: string;
  kind: V2Kind;
  question: string;
  recommendations: TextV2Item[];
  unresolved?: string;
}

export interface TextV2Case {
  caseId: string;
  format: typeof RUBRIC_TEXT_V2;
  usualCare: { harm: NeedSeverity | null; score?: Score | null } | null;
  decisions: TextV2Criterion[];
  unresolved?: string;
}

export interface TextV2Provenance {
  source: TextV2Case;
  sourceFile: string;
  sourceRubricSha256: string;
}

const CASE_KEYS = new Set(["caseId", "format", "usualCare", "decisions", "unresolved"]);
const CRITERION_KEYS = new Set(["id", "kind", "question", "omissionHarm", "recommendations", "unresolved"]);
const isOmissionNode = (d: Node, r: Node): boolean => r.id === `${label(d.id)}.0`;
// D162: addOn marks an add-on (a piece or extra, D146); an item without it is a main approach.
const ITEM_KEYS = new Set(["id", "text", "score", "harm", "optional", "addOn", "omissionHarm", "tag", "unresolved"]);
const LEGACY = new Set([
  "activation", "parts", "equivalents", "drugClass", "incompleteVersionOf", "alsoTakesCareOf", "counseling",
  "requirements", "requiredComponents", "needRole", "timingObligation", "timing", "harmIfDelayedOverride",
  "relativeHarmOverride", "harmIfRecommendedOverride", "harmIfNotAddressedOverride", "harmOverrides", "tags",
  "needSeverity", "tier",
]);
// The scorer's order, which includes "uncertain"; only the four harm values are valid in a v2 record.
const LEVELS = ["none", "uncertain", "mild", "moderate", "severe"];

type Node = Record<string, unknown>;

const isObject = (value: unknown): value is Node => typeof value === "object" && value !== null && !Array.isArray(value);
const isInt = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value);
const label = (value: unknown): string => (value === undefined || value === null ? "None" : String(value));

export function isTextV2(record: unknown): record is TextV2Case {
  return isObject(record) && record.format === RUBRIC_TEXT_V2;
}

export function validateTextV2(record: unknown, mode: V2Mode = "scoring"): { errors: string[]; warnings: string[] } {
  const errors: string[] = [];
  const warnings: string[] = [];
  const unknown = (where: string, field: string): void => {
    (mode === "draft" ? warnings : errors).push(`${where}: ${field} is unknown; scoring requires a reviewed value`);
  };
  const harm = (node: Node, field: string, where: string): NeedSeverity | null => {
    const value = node[field];
    if (value === undefined || value === null) unknown(where, field);
    else if (!V2_HARMS.includes(value as NeedSeverity)) errors.push(`${where}: ${field} must be none, mild, moderate or severe`);
    else return value as NeedSeverity;
    return null;
  };
  const note = (node: Node, where: string): void => {
    if (!("unresolved" in node)) return;
    const value = node.unresolved;
    if (mode === "scoring") errors.push(`${where}: unresolved elements are not admitted in scoring mode`);
    else if (typeof value !== "string" || !value.trim()) errors.push(`${where}: unresolved must be a nonblank note`);
    else warnings.push(`${where}: unresolved: ${value}`);
  };
  const floor = (score: number | null, level: NeedSeverity | null, where: string): void => {
    const need = score === null ? undefined : V2_SEVERITY_FLOOR[score];
    if (need && level !== null && LEVELS.indexOf(level) < LEVELS.indexOf(need)) warnings.push(`${where}: score ${score} needs error severity at least ${need} (D147)`);
  };
  const fields = (node: Node, allowed: Set<string>, where: string): void => {
    const keys = Object.keys(node);
    const legacy = keys.filter((key) => LEGACY.has(key)).sort();
    const extra = keys.filter((key) => !allowed.has(key) && !LEGACY.has(key)).sort();
    if (legacy.length) errors.push(`${where}: legacy fields are not supported: ${legacy.join(", ")}`);
    if (extra.length) errors.push(`${where}: unsupported fields: ${extra.join(", ")}`);
  };

  if (!isObject(record)) return { errors: ["case must be an object"], warnings: [] };
  fields(record, CASE_KEYS, "case");
  note(record, "case");
  if (record.format !== RUBRIC_TEXT_V2) errors.push(`format must equal ${RUBRIC_TEXT_V2}; other formats are not admitted`);
  if (typeof record.caseId !== "string" || !record.caseId) errors.push("caseId is required");
  const usualCare = record.usualCare;
  let usual: NeedSeverity | null = null;
  if (usualCare === undefined || usualCare === null) unknown("case", "usualCare");
  else if (!isObject(usualCare) || !("harm" in usualCare) || !Object.keys(usualCare).every((key) => key === "harm" || key === "score")) errors.push("usualCare must be an object with fields harm and score");
  else {
    usual = harm(usualCare, "harm", "usualCare");
    // D138: usual care is rated for appropriateness like an item; the scorer does not use it.
    if (usualCare.score === undefined || usualCare.score === null) unknown("usualCare", "score");
    else if (!isInt(usualCare.score) || usualCare.score < 1 || usualCare.score > 9) errors.push("usualCare: score must be an integer 1-9");
    else floor(usualCare.score, usual, "usualCare");
  }
  const decisions = record.decisions;
  if (!Array.isArray(decisions) || !decisions.length || !decisions.every(isObject)) {
    return { errors: [...errors, "decisions must be a nonempty list of objects"], warnings };
  }

  const first = decisions[0];
  const last = decisions[decisions.length - 1];
  const count = (kind: string): number => decisions.filter((d) => d.kind === kind).length;
  if (first.id !== "C2" || first.kind !== "followup" || first.question !== V2_FOLLOWUP_QUESTION || count("followup") !== 1) {
    errors.push(`C2 must be the one followup criterion, first, asking "${V2_FOLLOWUP_QUESTION}"`);
  }
  // D160: the counseling criterion is being retired; until v33 is rebuilt, at most one, last, standard question.
  if (count("counseling") > 1 || (count("counseling") === 1 && (last.kind !== "counseling" || last.question !== V2_COUNSELING_QUESTION))) {
    errors.push(`at most one counseling criterion, last, asking "${V2_COUNSELING_QUESTION}" (D160)`);
  }
  const ids = decisions.map((d) => d.id);
  const itemIds: unknown[] = [];
  const capped = (level: NeedSeverity | null, where: string): void => {
    if (level !== null && usual !== null && LEVELS.indexOf(level) > LEVELS.indexOf(usual)) {
      errors.push(`${where}: omission harm ${level} exceeds usual-care harm ${usual} (D130)`);
    }
  };

  for (const d of decisions) {
    const did = label(d.id);
    fields(d, CRITERION_KEYS, did);
    note(d, did);
    const kind = d.kind;
    const known = V2_KINDS.includes(kind as V2Kind);
    if (!known) errors.push(`${did}: kind must be one of ${V2_KINDS.join(", ")}`);
    if (typeof d.question !== "string" || !d.question.trim()) errors.push(`${did}: visible question is required`);
    if ("omissionHarm" in d) errors.push(`${did}: criterion omissionHarm is not supported; the omission is item ${did}.0 (D139)`);
    const items = d.recommendations;
    if (!Array.isArray(items) || !items.every(isObject)) {
      errors.push(`${did}: recommendations must be a list of objects`);
      continue;
    }
    const omission = items.filter((r) => isOmissionNode(d, r));
    if (kind === "counseling" && omission.length) {
      errors.push(`${did}: a counseling criterion has no ${did}.0 item; its omission harm comes from its items`);
    } else if (kind === "followup" || kind === "plan") {
      if (omission.length !== 1) errors.push(`${did}: needs exactly one omission item ${did}.0, "${V2_OMISSION_TEXT}" (D139)`);
      for (const r of omission) {
        if (r.text !== V2_OMISSION_TEXT || r.tag !== "none" || "optional" in r || "omissionHarm" in r) {
          errors.push(`${did}.0: the omission item has text "${V2_OMISSION_TEXT}", tag none, and no optional or omissionHarm (D139)`);
        }
      }
    }
    const actions = items.filter((r) => !isOmissionNode(d, r));
    if (!actions.length && kind !== "counseling") errors.push(`${did}: followup and plan criteria need items`);
    for (const r of items) {
      const rid = r.id;
      const where = label(rid);
      fields(r, ITEM_KEYS, where);
      note(r, where);
      itemIds.push(rid);
      if (typeof rid !== "string" || !rid) errors.push(`${did}: item IDs must be nonempty strings`);
      if (typeof r.text !== "string" || !r.text.trim()) errors.push(`${where}: visible item text is required`);
      if (!V2_TAGS.includes(r.tag as V2Tag)) errors.push(`${where}: tag must be exactly one of ${V2_TAGS.join(", ")}`);
      let score: number | null = null;
      if (r.score === undefined || r.score === null) unknown(where, "score");
      else if (!isInt(r.score) || r.score < 1 || r.score > 9) errors.push(`${where}: score must be an integer 1-9`);
      else score = r.score;
      const itemHarm = harm(r, "harm", where);
      floor(score, itemHarm, where);
      if ("addOn" in r && typeof r.addOn !== "boolean") errors.push(`${where}: addOn must be a boolean`);
      else if (r.addOn === true && isOmissionNode(d, r)) errors.push(`${where}: the omission item is a main approach, never an add-on (D162)`);
      if (isOmissionNode(d, r) && (kind === "followup" || kind === "plan")) {
        capped(itemHarm, where);
        continue;
      }
      if ("optional" in r && typeof r.optional !== "boolean") errors.push(`${where}: optional must be a boolean`);
      const optional = r.optional === true;
      if (optional && score !== null && score < 7) errors.push(`${where}: optional is allowed only on appropriate items (score 7-9) (D128)`);
      if (kind === "counseling" && !optional && (score === null || score >= 7)) {
        if (score !== null || "omissionHarm" in r) capped(harm(r, "omissionHarm", where), where);
      } else if ("omissionHarm" in r) {
        errors.push(`${where}: omissionHarm belongs only to required counseling items (counseling, score 7-9, not optional) (D127, D128)`);
      }
    }
    // D166: a rater may judge that a criterion is not a real need; silence is then error-free (.0 severity none)
    // and no main approach has to be appropriate.
    const silenceOk = omission.some((r) => r.harm === "none");
    if ((kind === "followup" || kind === "plan") && actions.length && actions.every((r) => isInt(r.score)) && !silenceOk
      && !actions.some((r) => (r.score as number) >= 7 && r.optional !== true && r.addOn !== true)) {
      errors.push(`${did}: at least one non-optional appropriate item (score 7-9) is required unless ${did}.0 has severity none (D166)`);
    }
  }
  if (ids.some((id) => typeof id !== "string" || !id) || new Set(ids).size !== ids.length) errors.push("criterion IDs must be unique nonempty strings");
  const named = [...ids, ...itemIds].filter((id): id is string => typeof id === "string");
  if (new Set(named).size !== named.length) errors.push("criterion and item IDs must be unique across the case");
  return { errors, warnings };
}

// Appropriate items that can meet the need: scored 7-9 and not optional (D128).
export function isRequired(item: TextV2Item): boolean {
  return item.score !== null && item.score >= 7 && item.optional !== true;
}

export function worstHarm(levels: NeedSeverity[]): NeedSeverity {
  return levels.reduce<NeedSeverity>((worst, level) => (V2_HARMS.indexOf(level) > V2_HARMS.indexOf(worst) ? level : worst), "none");
}

export function isOmissionItem(criterion: TextV2Criterion, item: TextV2Item): boolean {
  return item.id === `${criterion.id}.0`;
}

export function omissionItem(criterion: TextV2Criterion): TextV2Item | undefined {
  return criterion.recommendations.find((item) => isOmissionItem(criterion, item));
}

export function newOmissionItem(criterionId: string): TextV2Item {
  return { id: `${criterionId}.0`, text: V2_OMISSION_TEXT, score: null, harm: null, tag: "none" };
}

// The criterion's "Harm if missed": the .0 item's harm (D139). Counseling is computed from its required items
// (D127): "inactive" when it requires nothing, null while any required item is unrated.
export function criterionOmissionHarm(criterion: TextV2Criterion): NeedSeverity | null | "inactive" {
  if (criterion.kind !== "counseling") return omissionItem(criterion)?.harm ?? null;
  const required = criterion.recommendations.filter(isRequired);
  if (!required.length) return "inactive";
  const levels = required.map((item) => item.omissionHarm ?? null);
  return levels.every((level): level is NeedSeverity => level !== null) ? worstHarm(levels) : null;
}

function patchItem(criterion: TextV2Criterion, itemId: string, change: (item: TextV2Item) => TextV2Item): TextV2Criterion {
  return { ...criterion, recommendations: criterion.recommendations.map((item) => (item.id === itemId ? change(item) : item)) };
}

// Optional is allowed only on 7-9; a required counseling item needs its own omission harm, nothing else may carry one.
function reconcileItem(kind: V2Kind, item: TextV2Item): TextV2Item {
  const { optional, omissionHarm, ...rest } = item;
  const keepOptional = optional !== undefined && !(optional && (item.score === null || item.score < 7));
  const next: TextV2Item = { ...rest, ...(keepOptional ? { optional } : {}) };
  if (kind === "counseling" && next.optional !== true && (next.score === null ? omissionHarm !== undefined : next.score >= 7)) {
    return { ...next, omissionHarm: omissionHarm ?? null };
  }
  return next;
}

export function setV2Score(criterion: TextV2Criterion, itemId: string, score: Score): TextV2Criterion {
  return patchItem(criterion, itemId, (item) => reconcileItem(criterion.kind, { ...item, score }));
}

// D128: switching optional on pre-fills the harm if followed as none; the value stays explicit and editable.
export function setV2Optional(criterion: TextV2Criterion, itemId: string, on: boolean): TextV2Criterion {
  return patchItem(criterion, itemId, (item) => {
    if (on) return reconcileItem(criterion.kind, { ...item, optional: true, harm: "none" });
    const { optional: _optional, ...rest } = item;
    return reconcileItem(criterion.kind, rest);
  });
}

export function nextV2ItemId(record: TextV2Case, criterionId: string): string {
  const used = new Set(record.decisions.flatMap((d) => [d.id, ...d.recommendations.map((item) => item.id)]));
  let n = 1;
  while (used.has(`${criterionId}.${n}`)) n += 1;
  return `${criterionId}.${n}`;
}

// Tags are hidden, so a new item takes its kind's tag; plan items start as "none" for later analysis review.
export function newV2Item(record: TextV2Case, criterion: TextV2Criterion): TextV2Item {
  const tag: V2Tag = criterion.kind === "counseling" ? "counseling" : criterion.kind === "followup" ? "followup" : "none";
  return { id: nextV2ItemId(record, criterion.id), text: "", score: null, harm: null, tag, ...(criterion.kind === "counseling" ? { omissionHarm: null } : {}) };
}

// A new plan criterion goes before the standard counseling criterion. Existing IDs never change, so the v33
// crosswalk (D129) still resolves.
export function addV2Criterion(record: TextV2Case): { record: TextV2Case; added: string } {
  const used = new Set(record.decisions.flatMap((d) => [d.id, ...d.recommendations.map((item) => item.id)]));
  let n = record.decisions.length + 2;
  while (used.has(`C${n}`)) n += 1;
  const added = `C${n}`;
  const criterion: TextV2Criterion = { id: added, kind: "plan", question: "", recommendations: [newOmissionItem(added)] };
  criterion.recommendations = [...criterion.recommendations, newV2Item(record, criterion)];
  const at = record.decisions.findIndex((d) => d.kind === "counseling");
  const decisions = at < 0 ? [...record.decisions, criterion] : [...record.decisions.slice(0, at), criterion, ...record.decisions.slice(at)];
  return { record: { ...record, decisions }, added };
}

// Errors and warnings that name this criterion or one of its items.
export function v2Issues(criterion: TextV2Criterion, messages: string[]): string[] {
  const prefixes = [criterion.id, ...criterion.recommendations.map((item) => item.id)].map((id) => `${id}:`);
  return messages.filter((message) => prefixes.some((prefix) => message.startsWith(prefix)));
}

export function unratedV2Count(record: TextV2Case): number {
  return record.decisions.reduce((count, d) => count + d.recommendations.filter((item) => item.score === null || item.harm === null
    || (d.kind === "counseling" && isRequired(item) && item.omissionHarm == null)).length, 0);
}

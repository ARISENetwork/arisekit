import { isTextV2, validateTextV2, V2_OMISSION_TEXT, type TextV2Case, type V2Mode } from "./rubric-text-v2";
import { TEXT_V2_CURRENT_COMMIT, TEXT_V2_PIPELINE_V2_COMMIT } from "./text-v2-runtime";

// An upstream decision lets a harmless-omission criterion go without a 7-9 action. It holds from the
// earlier judge rules pin on; the current grading pin carries it unchanged.
const D166_PINS = new Set<unknown>([TEXT_V2_CURRENT_COMMIT, TEXT_V2_PIPELINE_V2_COMMIT]);

type Findings = { errors: string[]; warnings: string[] };

// The pinned validator cites upstream decision numbers, e.g. " (Dnnn)". Its messages stay identical to the pinned
// Python validator; only what people read drops the numbers.
export const withoutDecisionRefs = (message: string): string => message.replace(/ \(D\d{3}(?:, D\d{3})*\)/g, "");

export function validateTextV2ForDisplay(record: unknown, mode: V2Mode, provenance: Record<string, unknown> = {}): Findings {
  const { errors, warnings } = validateTextV2ForProject(record, mode, provenance);
  return { errors: errors.map(withoutDecisionRefs), warnings: warnings.map(withoutDecisionRefs) };
}

export function validateTextV2ForProject(record: unknown, mode: V2Mode, provenance: Record<string, unknown> = {}): Findings {
  const result = validateTextV2(record, mode);
  if (!D166_PINS.has(provenance.judge_scoring_source_commit) || !isTextV2(record) || !Array.isArray(record.decisions)) return result;
  const permitted = new Set<string>();
  for (const criterion of record.decisions) {
    if (!criterion || typeof criterion.id !== "string" || !criterion.id || (criterion.kind !== "followup" && criterion.kind !== "plan") || !Array.isArray(criterion.recommendations)) continue;
    const omissions = criterion.recommendations.filter(item => item && item.id === `${criterion.id}.0`);
    if (omissions.length !== 1) continue;
    const omission = omissions[0];
    if (omission.text === V2_OMISSION_TEXT && omission.tag === "none" && omission.harm === "none" &&
        omission.score !== null && Number.isInteger(omission.score) && omission.score >= 1 && omission.score <= 9 &&
        (omission.addOn === undefined || omission.addOn === false) && !("optional" in omission) && !("omissionHarm" in omission)) {
      permitted.add(`${criterion.id}: at least one non-optional appropriate item (score 7-9) is required`);
    }
  }
  return { ...result, errors: result.errors.filter(error => !permitted.has(error)) };
}

export function textV2ScoringErrors(record: TextV2Case, provenance: Record<string, unknown> = {}): string[] {
  const errors = validateTextV2ForProject(record, "scoring", provenance).errors;
  if (errors.length) return errors;
  return [...errors,
    ...(record.decisions.some(criterion => criterion.kind === "counseling")
      ? ["Scoring needs the current rubric format; rebuild the legacy counseling criterion first"] : [])];
}

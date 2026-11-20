import { createHash } from "node:crypto";

import type { TextV2Case } from "./rubric-text-v2";

// The text rubric format binds the native rubric with compact UTF-8 JSON, unlike legacy answer tables.
export function textV2Json(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(textV2Json).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const object = value as Record<string, unknown>;
    const compare = (a: string, b: string): number => {
      const left = Array.from(a, char => char.codePointAt(0)!);
      const right = Array.from(b, char => char.codePointAt(0)!);
      for (let i = 0; i < Math.min(left.length, right.length); i += 1) if (left[i] !== right[i]) return left[i] - right[i];
      return left.length - right.length;
    };
    return `{${Object.keys(object).sort(compare).map(key => `${JSON.stringify(key)}:${textV2Json(object[key])}`).join(",")}}`;
  }
  if (typeof value === "number" && !Number.isSafeInteger(value)) throw new Error("Rubric identities require safe integer ratings.");
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new Error("Rubric identities require JSON values.");
  return encoded;
}

export const textV2Sha256 = (record: unknown): string => createHash("sha256").update(textV2Json(record), "utf8").digest("hex");

// Python's rubric_text_sha256 (pipeline_v2_slots.text_sha256): upstream project_for_judge without its rubricSha256,
// so only what the judge sees (IDs, kinds, questions and item text, no `.0` omission items) is bound.
export function textV2JudgeTextSha256(record: TextV2Case): string {
  return textV2Sha256({
    profile: "text-rubric-v2", caseId: record.caseId,
    decisions: record.decisions.map(d => ({
      id: d.id, question: d.question, kind: d.kind,
      rows: d.recommendations.filter(r => r.id !== `${d.id}.0`).map(r => ({ id: r.id, text: r.text })),
    })),
  });
}

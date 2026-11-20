import type { CasesetJudgeOutput, ScoredRecord } from "@/lib/caseset/types";

export interface EvidenceSpan { key: string; label: string; evidence: string }
export interface Segment { text: string; keys: string[] }

export const spanKey = {
  row: (decisionId: string, i: number): string => `${decisionId}:r${i}`,
  unmatched: (decisionId: string, i: number): string => `${decisionId}:u${i}`,
  offRubric: (i: number): string => `off:${i}`,
};

// Python's re `\s` on str, which differs from JavaScript's: it adds U+001C-001F and U+0085 and lacks U+FEFF.
const WS_CODES = new Set([9, 10, 11, 12, 13, 32, 0x1c, 0x1d, 0x1e, 0x1f, 0x85, 0xa0, 0x1680, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000]);
const isSpace = (ch: string): boolean => { const c = ch.charCodeAt(0); return WS_CODES.has(c) || (c >= 0x2000 && c <= 0x200a); };

// Mirrors pipeline/e2e/judge.py _norm (whitespace runs become one space, ends trimmed).
// index[i] is the position in `text` of normalized character i.
export function normalize(text: string): { norm: string; index: number[] } {
  const chars: string[] = [];
  const index: number[] = [];
  for (let i = 0; i < text.length; i += 1) {
    if (!isSpace(text[i])) {
      chars.push(text[i]);
      index.push(i);
    } else if (chars.length && chars[chars.length - 1] !== " ") {
      chars.push(" ");
      index.push(i);
    }
  }
  if (chars[chars.length - 1] === " ") {
    chars.pop();
    index.pop();
  }
  return { norm: chars.join(""), index };
}

// Splits `text` into runs tagged with the spans covering them. Evidence not found is returned, never dropped.
export function highlight(text: string, spans: EvidenceSpan[]): { segments: Segment[]; missing: EvidenceSpan[] } {
  const { norm, index } = normalize(text);
  const owners: string[][] = Array.from({ length: text.length }, () => []);
  const missing: EvidenceSpan[] = [];
  for (const span of spans) {
    const needle = normalize(span.evidence).norm;
    const at = needle ? norm.indexOf(needle) : -1;
    if (at < 0) {
      missing.push(span);
      continue;
    }
    for (let i = index[at]; i <= index[at + needle.length - 1]; i += 1) owners[i].push(span.key);
  }
  const segments: Segment[] = [];
  for (let i = 0; i < text.length; i += 1) {
    const last = segments[segments.length - 1];
    if (last && last.keys.join("\n") === owners[i].join("\n")) last.text += text[i];
    else segments.push({ text: text[i], keys: owners[i] });
  }
  return { segments, missing };
}

export function judgeSpans(out: CasesetJudgeOutput): EvidenceSpan[] {
  const spans: EvidenceSpan[] = [];
  for (const [decisionId, d] of Object.entries(out.decisions)) {
    (d.recommended ?? []).forEach((rec, i) => spans.push({ key: spanKey.row(decisionId, i), label: `${decisionId} ${rec.rowId}`, evidence: rec.evidence }));
    (d.unmatched ?? []).forEach((u, i) => spans.push({ key: spanKey.unmatched(decisionId, i), label: `${decisionId} unmatched ${i + 1}`, evidence: u.evidence }));
  }
  out.offRubric.forEach((o, i) => spans.push({ key: spanKey.offRubric(i), label: `Off-rubric ${i + 1}`, evidence: o.evidence }));
  return spans;
}

export function provisionalReasons(scored: ScoredRecord): string[] {
  const decisions = Object.entries(scored.decisions).filter(([, d]) => d.state === "provisional").map(([id]) => id);
  return [
    ...(decisions.length ? [`unmatched statements read provisionally in ${decisions.join(", ")}`] : []),
    ...(scored.offRubricProvisional ? ["actionable off-rubric harm"] : []),
  ];
}

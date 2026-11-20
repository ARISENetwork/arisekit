import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { inside, listModels, listVersionLabels } from "@/lib/caseset/paths";
import { readJsonl } from "@/lib/caseset/read";
import { textSha256 } from "@/lib/caseset/hash";
import type { Item, ResponseRecord } from "@/lib/caseset/types";

// Which case text changed after an output was made. Errors edits count as Solution edits: both feed the rubric only.
export type OutdatedReason = "task" | "solution";
export type EditedField = "task" | "solutions" | "errors";

export interface CaseEdit {
  edited_at: string;
  changed: EditedField[];
  prior_source: string;
  // Outputs that existed when the case text changed, identified by content so a regenerated file is not tagged.
  // A response also records the input it answered (absent in edits saved before it was recorded), so the same text
  // collected again for the edited Task is not tagged.
  rubrics: { version: string; file_sha256: string | null }[];
  responses: { model: string; id: string; trial: number; response_sha256: string | null; input_sha256?: string | null }[];
}

const fileSha256 = (file: string): string | null => existsSync(file) ? createHash("sha256").update(readFileSync(file)).digest("hex") : null;

function rubricSha256(dir: string, caseId: string, version: string): string | null {
  const at = (suffix: string): string => inside(dir, "answer-tables", `${caseId}.${version}${suffix}`);
  return fileSha256(at(".json")) ?? fileSha256(at(".status.json"));
}

const responseSha256 = (response: string | null | undefined): string | null => typeof response === "string" ? textSha256(response) : null;

// Responses only see the Task, so only a Task edit puts them out of date.
export function caseOutputs(dir: string, caseId: string, changed: EditedField[]): Pick<CaseEdit, "rubrics" | "responses"> {
  const rubrics = listVersionLabels(dir, caseId).map((version) => ({ version, file_sha256: rubricSha256(dir, caseId, version) }));
  if (!changed.includes("task")) return { rubrics, responses: [] };
  const items = new Set(readJsonl<Item>(inside(dir, "items.jsonl")).filter((item) => (item.metadata?.base_id ?? item.id) === caseId).map((item) => item.id));
  const responses = listModels(dir).flatMap((model) => readJsonl<ResponseRecord>(inside(dir, "results", "responses", `${model}.jsonl`))
    .filter((record) => items.has(record.id))
    .map((record) => ({ model, id: record.id, trial: record.trial ?? 1, response_sha256: responseSha256(record.response), input_sha256: record.input_sha256 ?? null })));
  return { rubrics, responses };
}

export function caseEdits(source: unknown): CaseEdit[] {
  const edits = (source as { source_provenance?: { edits?: unknown } }).source_provenance?.edits;
  return Array.isArray(edits) ? edits as CaseEdit[] : [];
}

const reasonOf = (edits: CaseEdit[]): OutdatedReason | null => !edits.length ? null : edits.some((edit) => edit.changed.includes("task")) ? "task" : "solution";

// A reviewed copy of an out-of-date rubric is out of date too, even when it was saved after the edit.
export function outdatedRubrics(dir: string, caseId: string, edits: CaseEdit[], tables: { version: string; basedOn?: { version: string } }[]): Map<string, OutdatedReason> {
  const outdated = new Map<string, OutdatedReason>();
  if (!edits.length) return outdated;
  for (const table of tables) {
    const sha = rubricSha256(dir, caseId, table.version);
    const reason = reasonOf(edits.filter((edit) => edit.rubrics.some((rubric) => rubric.version === table.version && rubric.file_sha256 === sha)));
    if (reason) outdated.set(table.version, reason);
  }
  for (let changed = true; changed;) {
    changed = false;
    for (const table of tables) {
      const inherited = table.basedOn && outdated.get(table.basedOn.version);
      if (inherited && !outdated.has(table.version)) { outdated.set(table.version, inherited); changed = true; }
    }
  }
  return outdated;
}

export function outdatedResponse(edits: CaseEdit[], model: string, id: string, trial: number, response: string | null, inputSha256: string | null = null): OutdatedReason | null {
  const sha = responseSha256(response);
  const sameInput = (recorded: string | null | undefined): boolean => !recorded || recorded === inputSha256;
  return reasonOf(edits.filter((edit) => edit.responses.some((r) => r.model === model && r.id === id && r.trial === trial && r.response_sha256 === sha && sameInput(r.input_sha256))));
}

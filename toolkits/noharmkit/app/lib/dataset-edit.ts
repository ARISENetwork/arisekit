import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { assertCase, casesetDir, inside, list } from "@/lib/caseset/paths";
import { readJson, readJsonl } from "@/lib/caseset/read";
import type { CasePage, Item, ResponseRecord } from "@/lib/caseset/types";
import type { CaseSource } from "@/lib/types";
import { datasetFields } from "./dataset-fields";
import { caseEdits, caseOutputs, type CaseEdit, type OutdatedReason } from "./dataset-outdated";
import { parseDataset, type DatasetCase } from "./dataset-import";

export class DatasetEditConflict extends Error {}

export function caseHasResults(dir: string, id: string): boolean {
  if (list(dir, "answer-tables").some((file) => file.startsWith(`${id}.`)) || list(dir, "answer-tables", "history").some((file) => file.startsWith(`${id}.`))) return true;
  const items = new Set(readJsonl<Item>(inside(dir, "items.jsonl")).filter((item) => (item.metadata?.base_id ?? item.id) === id).map((item) => item.id));
  return list(dir, "results", "responses").filter((file) => file.endsWith(".jsonl")).some((file) => readJsonl<ResponseRecord>(inside(dir, "results", "responses", file)).some((row) => items.has(row.id)));
}

export interface DatasetOutdated { rubric: OutdatedReason | null; responses: number }

// The rubric needs regenerating while no current passing rubric exists alongside the out-of-date ones.
export function datasetOutdated(page: Pick<CasePage, "tables" | "responses">): DatasetOutdated {
  const stale = page.tables.filter((table) => table.outdated);
  const current = page.tables.some((table) => table.status === "pass" && !table.outdated);
  return {
    rubric: !stale.length || current ? null : stale.some((table) => table.outdated === "task") ? "task" : "solution",
    responses: page.responses.filter((row) => row.outdated && !row.responseError).length,
  };
}

export function saveDatasetCase(root: string, project: string, id: string, value: DatasetCase, basis: DatasetCase): void {
  const dir = casesetDir(root, project);
  assertCase(dir, id);
  const sourcePath = inside(dir, "cases", `${id}.json`);
  const source = readJson<CaseSource & { source_provenance?: Record<string, unknown> }>(sourcePath);
  const original = datasetFields(source);
  if (JSON.stringify(original) !== JSON.stringify({ task: basis.task, solutions: basis.solutions, errors: basis.errors })) throw new DatasetEditConflict("This case changed while you were editing. Refresh before saving.");
  const [updated] = parseDataset(JSON.stringify(value), "case.json");
  if (JSON.stringify(original) === JSON.stringify({ task: updated.task, solutions: updated.solutions, errors: updated.errors })) return;
  const itemsPath = inside(dir, "items.jsonl");
  const items = readJsonl<Item>(itemsPath);
  const own = items.filter((item) => (item.metadata?.base_id ?? item.id) === id);
  if (own.length !== 1 || own[0].id !== id) throw new DatasetEditConflict("This case has derived items. Add a new case to make changes.");
  const changed = (["task", "solutions", "errors"] as const).filter((field) => JSON.stringify(original[field]) !== JSON.stringify(updated[field]));
  const historyId = randomUUID();
  const folder = inside(dir, "cases", "history", id, historyId);
  mkdirSync(folder, { recursive: true });
  writeFileSync(inside(folder, "source.json"), readFileSync(sourcePath), { flag: "wx" });
  writeFileSync(inside(folder, "items.jsonl"), readFileSync(itemsPath), { flag: "wx" });
  const editedAt = new Date().toISOString();
  // Project-relative, so the record stays valid when the project is copied or exported.
  const priorSource = `cases/history/${id}/${historyId}/source.json`;
  const edit: CaseEdit = { edited_at: editedAt, changed, prior_source: priorSource, ...caseOutputs(dir, id, changed) };
  const reference = updated.solutions.length === 1 ? updated.solutions[0] : updated.solutions.map((solution, index) => `Acceptable solution ${index + 1}:\n${solution}`).join("\n\n");
  const record = { ...source, presentation: updated.task, recommendations: reference + (updated.errors ? `\n\nAuthor-provided error criteria (provisional harm levels):\n${updated.errors}` : ""), errors: updated.errors, source_provenance: { ...source.source_provenance, supplied_solutions: updated.solutions, edited_at: editedAt, prior_source: priorSource, edits: [...caseEdits(source), edit] } };
  writeFileSync(sourcePath, JSON.stringify(record, null, 2) + "\n");
  writeFileSync(itemsPath, items.map((item) => JSON.stringify(item.id === id ? { ...item, prompt: updated.task } : item)).join("\n") + "\n");
}

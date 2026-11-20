import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { casesetDir, inside } from "@/lib/caseset/paths";
import { emptyDatasetDrafts, type DatasetDraftState } from "./dataset-draft-state";

export class DatasetDraftConflict extends Error {}

function validateState(value: unknown): asserts value is DatasetDraftState {
  if (!value || typeof value !== "object") throw new TypeError("Provide the dataset draft state.");
  const state = value as DatasetDraftState;
  if (!Number.isSafeInteger(state.revision) || state.revision < 0 || !(state.selected === null || typeof state.selected === "string")) throw new TypeError("Provide a valid draft revision and selection.");
  for (const records of [state.drafts, state.bases]) {
    if (!records || typeof records !== "object" || Array.isArray(records)) throw new TypeError("Provide draft fields and original case fields.");
    for (const record of Object.values(records)) {
      if (!record || typeof record !== "object" || typeof record.task !== "string" || typeof record.errors !== "string" || !Array.isArray(record.solutions) || !record.solutions.length || !record.solutions.every((solution) => typeof solution === "string") || record.id !== undefined && typeof record.id !== "string" || record.source_item_id !== undefined && typeof record.source_item_id !== "string") throw new TypeError("Each draft needs Task, Solutions, and Errors text. Incomplete fields may be blank.");
    }
  }
}

export function readDatasetDrafts(root: string, project: string): DatasetDraftState {
  const file = inside(casesetDir(root, project), "drafts", "dataset.json");
  if (!existsSync(file)) return emptyDatasetDrafts();
  const state: unknown = JSON.parse(readFileSync(file, "utf8"));
  validateState(state);
  return state;
}

export function saveDatasetDrafts(root: string, project: string, state: unknown): DatasetDraftState {
  validateState(state);
  const dir = casesetDir(root, project);
  const current = readDatasetDrafts(root, project);
  if (state.revision !== current.revision) throw new DatasetDraftConflict("Saved drafts changed since this page loaded. Keep your text and reopen the project before saving again.");
  const saved = { ...state, revision: current.revision + 1 };
  mkdirSync(inside(dir, "drafts"), { recursive: true });
  const temporary = inside(dir, "drafts", `${randomUUID()}.tmp`);
  writeFileSync(temporary, JSON.stringify(saved, null, 2) + "\n", { flag: "wx" });
  renameSync(temporary, inside(dir, "drafts", "dataset.json"));
  return saved;
}

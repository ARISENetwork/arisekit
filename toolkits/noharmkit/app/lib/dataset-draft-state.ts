import type { DatasetCase } from "./dataset-import";

export interface DatasetDraftState {
  revision: number;
  selected: string | null;
  drafts: Record<string, DatasetCase>;
  bases: Record<string, DatasetCase>;
}

export function emptyDatasetDrafts(): DatasetDraftState {
  return { revision: 0, selected: null, drafts: {}, bases: {} };
}

export function datasetSelection(cases: string[], state: DatasetDraftState, requested: string | null): string {
  if (requested && cases.includes(requested)) return requested;
  const saved = state.selected;
  if (saved && (saved === "new" || state.drafts[saved] || cases.includes(saved))) return saved;
  return cases[0] ?? "new";
}

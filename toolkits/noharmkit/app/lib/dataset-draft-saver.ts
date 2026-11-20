import type { DatasetDraftState } from "./dataset-draft-state";

export type DraftSaveStatus = { state: "saved" | "saving" | "error"; error?: string };

export function createDatasetDraftSaver(initialRevision: number, save: (state: DatasetDraftState) => Promise<number>, notify: (status: DraftSaveStatus) => void): { enqueue: (state: DatasetDraftState) => void; flush: () => Promise<boolean>; pending: () => boolean } {
  let revision = initialRevision;
  let latest: DatasetDraftState | null = null;
  let running: Promise<boolean> | null = null;
  const flush = (): Promise<boolean> => {
    if (running) return running;
    if (!latest) return Promise.resolve(true);
    notify({ state: "saving" });
    running = (async (): Promise<boolean> => {
      while (latest) {
        const state = latest;
        latest = null;
        try { revision = await save({ ...state, revision }); }
        catch (caught) {
          latest ??= state;
          notify({ state: "error", error: (caught as Error).message });
          return false;
        }
      }
      notify({ state: "saved" });
      return true;
    })().finally(() => { running = null; });
    return running;
  };
  return { enqueue: (state) => { latest = state; void flush(); }, flush, pending: () => Boolean(latest || running) };
}

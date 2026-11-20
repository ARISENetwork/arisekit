import type { Answers } from "@/lib/caseset/judgment-review-saving";

// The browser copy of a review: every change is written here at once, before any save to the project. Answers a
// reviewer did not choose, or that went out of date, are kept aside under their own keys and never deleted.

export interface BrowserCopy extends Answers {
  draftId: string;
  // The project revision these answers build on; null before the draft's first save.
  serverRevision: number | null;
  // True until the project confirms a save of exactly these answers.
  unsaved: boolean;
  changedAt: string;
}

export interface CopyStore { get(key: string): string | null; set(key: string, value: string): void; remove(key: string): void; has(key: string): boolean }

export type KeptReason = "unchosen" | "superseded";

export function browserCopyKey(parts: { account: string; reviewer: string; project: string; model: string; id: string; trial: number; judgmentSha256: string }): string {
  return `noharm:judgment-review:v2:${parts.account}:${parts.reviewer}:${parts.project}:${parts.model}:${parts.id}:${parts.trial}:${parts.judgmentSha256}`;
}

// Storage can be full or blocked. The project save still runs, so a failed browser write is not fatal.
export function browserStore(): CopyStore {
  const attempt = <T>(run: () => T, fallback: T): T => { try { return run(); } catch { return fallback; } };
  return {
    get: (key) => attempt(() => window.localStorage.getItem(key), null),
    set: (key, value) => attempt(() => window.localStorage.setItem(key, value), undefined),
    remove: (key) => attempt(() => window.localStorage.removeItem(key), undefined),
    has: (key) => attempt(() => window.localStorage.getItem(key) !== null, false),
  };
}

export function sameAnswers(a: Answers, b: Answers): boolean {
  const same = (x: Record<string, string>, y: Record<string, string>): boolean => {
    const keys = Object.keys(x);
    return keys.length === Object.keys(y).length && keys.every((key) => x[key] === y[key]);
  };
  return same(a.verdicts, b.verdicts) && same(a.evidence, b.evidence);
}

export function readCopy(store: CopyStore, key: string): BrowserCopy | null {
  try {
    const raw = store.get(key);
    const copy = raw ? JSON.parse(raw) as Partial<BrowserCopy> : null;
    if (!copy || typeof copy.draftId !== "string" || !copy.verdicts || typeof copy.verdicts !== "object" || !copy.evidence || typeof copy.evidence !== "object") return null;
    return copy as BrowserCopy;
  } catch {
    return null;
  }
}

export function writeCopy(store: CopyStore, key: string, copy: BrowserCopy | null): void {
  if (copy) store.set(key, JSON.stringify(copy));
  else store.remove(key);
}

// Each set kept aside gets its own key, so a second conflict never overwrites the first.
export function keepAside(store: CopyStore, key: string, copy: BrowserCopy, reason: KeptReason, at: string): string {
  const base = `${key}:kept:${reason}:${at}`;
  let kept = base;
  for (let n = 2; store.has(kept); n += 1) kept = `${base}:${n}`;
  store.set(kept, JSON.stringify(copy));
  return kept;
}

export type LoadChoice = { kind: "none" } | { kind: "offer"; copy: BrowserCopy } | { kind: "conflict"; copy: BrowserCopy };

// What to do with the browser copy when the review loads. A copy is offered back only when it builds on the
// project's current revision; a copy behind a newer save is a conflict, and the reviewer picks one set.
export function loadChoice(copy: BrowserCopy | null, server: { draft: { draftId: string; revision: number } | null; outOfDate: boolean }, shown: Answers): LoadChoice {
  if (!copy?.unsaved || server.outOfDate || sameAnswers(copy, shown)) return { kind: "none" };
  if (!server.draft) return { kind: "offer", copy };
  return copy.draftId === server.draft.draftId && (copy.serverRevision ?? 0) >= server.draft.revision ? { kind: "offer", copy } : { kind: "conflict", copy };
}

export interface CopySide extends Answers { draftId: string; serverRevision: number | null; unsaved: boolean }

// The reviewer chose `keep` over `drop`: `drop` is kept aside under its own key and `keep` becomes the live copy.
// Answers that still need saving stay marked unsaved until the project confirms them.
export function choose(store: CopyStore, key: string, keep: CopySide, drop: CopySide, at: string): BrowserCopy {
  keepAside(store, key, { ...drop, changedAt: at }, "unchosen", at);
  const live = { ...keep, changedAt: at };
  writeCopy(store, key, live);
  return live;
}

// Before a new draft replaces an out-of-date one, any unsaved live copy moves aside, whatever draft it belongs to.
// Saved answers are already on the project, which keeps the replaced draft under superseded/.
export function startAgain(store: CopyStore, key: string, at: string): void {
  const copy = readCopy(store, key);
  if (copy?.unsaved) keepAside(store, key, copy, "superseded", at);
  writeCopy(store, key, null);
}

// After the project confirms a save of `saved`: the live copy is marked saved only if it holds exactly those answers,
// so newer changes made while the save was in flight stay unsaved.
export function markSaved(store: CopyStore, key: string, saved: Answers & { draftId: string; serverRevision: number }, at: string): void {
  const copy = readCopy(store, key);
  if (copy && !sameAnswers(copy, saved)) return;
  writeCopy(store, key, { verdicts: saved.verdicts, evidence: saved.evidence, draftId: saved.draftId, serverRevision: saved.serverRevision, unsaved: false, changedAt: copy?.changedAt ?? at });
}

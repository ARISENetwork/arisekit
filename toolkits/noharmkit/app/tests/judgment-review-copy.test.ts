import assert from "node:assert/strict";
import { test } from "node:test";

import {
  choose, keepAside, loadChoice, markSaved, readCopy, startAgain, writeCopy,
  type BrowserCopy, type CopySide, type CopyStore,
} from "../lib/caseset/judgment-review-copy";
import type { Answers } from "../lib/caseset/judgment-review-saving";

const KEY = "noharm:judgment-review:v2:local:dw:p:m:Case001:1:abc";
const AT = "2026-11-14T12:00:00.000Z";

function memory(): CopyStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    get: (key) => data.get(key) ?? null,
    set: (key, value) => { data.set(key, value); },
    remove: (key) => { data.delete(key); },
    has: (key) => data.has(key),
  };
}

const answers = (verdict: "complete" | "partial" | "notAddressed"): Answers => ({ verdicts: { "C2/C2.1": verdict }, evidence: {} });
const copy = (verdict: "complete" | "partial" | "notAddressed", over: Partial<BrowserCopy> = {}): BrowserCopy =>
  ({ ...answers(verdict), draftId: "d1", serverRevision: 3, unsaved: true, changedAt: AT, ...over });
const side = (verdict: "complete" | "partial" | "notAddressed", over: Partial<CopySide> = {}): CopySide =>
  ({ ...answers(verdict), draftId: "d1", serverRevision: 3, unsaved: false, ...over });
const kept = (store: ReturnType<typeof memory>): Array<[string, BrowserCopy]> =>
  [...store.data.entries()].filter(([key]) => key.startsWith(`${KEY}:kept:`)).map(([key, value]) => [key, JSON.parse(value) as BrowserCopy]);

test("an unsaved copy is offered only when it builds on the project's current revision", () => {
  const server = { draft: { draftId: "d1", revision: 3 }, outOfDate: false };
  assert.equal(loadChoice(copy("partial"), server, answers("complete")).kind, "offer");
  assert.equal(loadChoice(copy("partial", { serverRevision: 4 }), server, answers("complete")).kind, "offer");
  assert.equal(loadChoice(copy("partial", { serverRevision: 2 }), server, answers("complete")).kind, "conflict", "an older copy never silently replaces a newer save");
  assert.equal(loadChoice(copy("partial", { draftId: "other" }), server, answers("complete")).kind, "conflict");
  assert.equal(loadChoice(copy("partial", { serverRevision: null }), { draft: null, outOfDate: false }, answers("complete")).kind, "offer");
});

test("nothing is offered for a saved copy, identical answers, or an out-of-date draft", () => {
  const server = { draft: { draftId: "d1", revision: 3 }, outOfDate: false };
  assert.equal(loadChoice(null, server, answers("complete")).kind, "none");
  assert.equal(loadChoice(copy("partial", { unsaved: false }), server, answers("complete")).kind, "none");
  assert.equal(loadChoice(copy("complete"), server, answers("complete")).kind, "none");
  assert.equal(loadChoice(copy("partial"), { ...server, outOfDate: true }, answers("complete")).kind, "none");
});

test("keeping this tab's answers after a conflict leaves them unsaved until the project confirms them", () => {
  const store = memory();
  // Keep this tab's answers over the other tab's revision 5.
  choose(store, KEY, side("partial", { draftId: "d1", serverRevision: 5, unsaved: true }), side("notAddressed", { serverRevision: 5 }), AT);
  const live = readCopy(store, KEY)!;
  assert.equal(live.unsaved, true);
  assert.equal(live.verdicts["C2/C2.1"], "partial");
  // The save then fails and the tab reloads: the copy is offered back against revision 5.
  assert.equal(loadChoice(live, { draft: { draftId: "d1", revision: 5 }, outOfDate: false }, answers("notAddressed")).kind, "offer");
  // Once the save is confirmed, the copy is marked saved.
  markSaved(store, KEY, { ...answers("partial"), draftId: "d1", serverRevision: 6 }, AT);
  assert.deepEqual([readCopy(store, KEY)!.unsaved, readCopy(store, KEY)!.serverRevision], [false, 6]);
  assert.equal(kept(store)[0][1].verdicts["C2/C2.1"], "notAddressed", "the other tab's answers are kept aside");
});

test("using the browser copy keeps the on-screen answers aside first", () => {
  const store = memory();
  writeCopy(store, KEY, copy("partial"));
  choose(store, KEY, side("partial", { unsaved: true }), side("complete"), AT);
  assert.equal(readCopy(store, KEY)!.verdicts["C2/C2.1"], "partial");
  assert.equal(readCopy(store, KEY)!.unsaved, true);
  assert.equal(kept(store).length, 1);
  assert.equal(kept(store)[0][1].verdicts["C2/C2.1"], "complete");
});

test("each set kept aside has its own key, so a second conflict never overwrites the first", () => {
  const store = memory();
  choose(store, KEY, side("partial", { unsaved: true }), side("complete"), AT);
  choose(store, KEY, side("notAddressed", { unsaved: true }), side("partial", { unsaved: true }), AT);
  keepAside(store, KEY, copy("complete"), "unchosen", AT);
  const sets = kept(store);
  assert.equal(sets.length, 3);
  assert.equal(new Set(sets.map(([key]) => key)).size, 3);
  assert.deepEqual(sets.map(([, set]) => set.verdicts["C2/C2.1"]).sort(), ["complete", "complete", "partial"]);
});

test("start again moves any unsaved copy aside, whatever draft it belongs to, and later saves never delete it", () => {
  const store = memory();
  writeCopy(store, KEY, copy("partial", { draftId: "unrelated" }));
  startAgain(store, KEY, AT);
  assert.equal(readCopy(store, KEY), null);
  const [[keptKey, set]] = kept(store);
  assert.match(keptKey, /:kept:superseded:/);
  assert.equal(set.draftId, "unrelated");
  assert.equal(set.unsaved, true);
  // The new draft saves; the superseded browser copy stays.
  writeCopy(store, KEY, copy("complete", { draftId: "new", serverRevision: null }));
  markSaved(store, KEY, { ...answers("complete"), draftId: "new", serverRevision: 1 }, AT);
  assert.ok(store.has(keptKey));
});

test("start again does not keep a copy that is already on the project", () => {
  const store = memory();
  writeCopy(store, KEY, copy("partial", { unsaved: false }));
  startAgain(store, KEY, AT);
  assert.equal(readCopy(store, KEY), null);
  assert.equal(kept(store).length, 0);
});

test("a confirmed save leaves newer unsaved answers unsaved", () => {
  const store = memory();
  writeCopy(store, KEY, copy("notAddressed", { serverRevision: 3 }));
  markSaved(store, KEY, { ...answers("partial"), draftId: "d1", serverRevision: 4 }, AT);
  const live = readCopy(store, KEY)!;
  assert.deepEqual([live.unsaved, live.verdicts["C2/C2.1"]], [true, "notAddressed"]);
});

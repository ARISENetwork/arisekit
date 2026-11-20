import assert from "node:assert/strict";
import { test } from "node:test";

import { BASE_NOT_ON_RECORD, JUDGMENT_CHANGED, JUDGMENT_NOT_CURRENT, REVIEW_ALREADY_FINISHED } from "../lib/caseset/judgment-review";
import { classifySave, DraftSaver, type SaveProblem, type SaverState, type SendResult } from "../lib/caseset/judgment-review-saving";

interface Call { draftId: string; replaces: number | null; value: string; resolve: (result: SendResult) => void }

function harness(start: { draftId?: string; revision?: number | null } = {}) {
  const calls: Call[] = [];
  const timers = new Map<number, { run: () => void; ms: number }>();
  const states: SaverState[] = [];
  const problems: SaveProblem[] = [];
  const saved: Array<[string, string, number]> = [];
  let next = 0;
  let ids = 0;
  const saver = new DraftSaver<string>({
    send: (draftId, replaces, value) => new Promise((resolve) => calls.push({ draftId, replaces, value, resolve })),
    onState: (state) => states.push(state),
    onProblem: (problem) => problems.push(problem),
    onSaved: (value, draftId, revision) => saved.push([value, draftId, revision]),
    newDraftId: () => `new-${++ids}`,
    schedule: (run, ms) => { timers.set(++next, { run, ms }); return next; },
    cancel: (timer) => { timers.delete(timer as number); },
  }, start.draftId ?? "d1", start.revision ?? null);
  const fire = (): void => {
    const [id, timer] = [...timers.entries()][0];
    timers.delete(id);
    timer.run();
  };
  const tick = (): Promise<void> => new Promise((resolve) => setImmediate(resolve));
  return { saver, calls, timers, states, problems, saved, fire, tick };
}

test("changes within the delay send once, with the latest value", async () => {
  const h = harness();
  h.saver.change("a");
  h.saver.change("b");
  assert.equal(h.timers.size, 1);
  assert.equal([...h.timers.values()][0].ms, 3000);
  h.fire();
  assert.deepEqual(h.calls.map((c) => [c.draftId, c.replaces, c.value]), [["d1", null, "b"]]);
  h.calls[0].resolve({ kind: "saved", revision: 1 });
  await h.tick();
  assert.equal(h.states.at(-1)?.status, "saved");
  assert.equal(h.saver.revision, 1);
});

test("one save in flight; newer changes wait and replace each other", async () => {
  const h = harness();
  h.saver.change("a");
  h.fire();
  h.saver.change("b");
  h.saver.change("c");
  h.fire();
  assert.equal(h.calls.length, 1, "no second request while one is in flight");
  h.calls[0].resolve({ kind: "saved", revision: 1 });
  await h.tick();
  assert.deepEqual(h.calls.map((c) => c.value), ["a", "c"]);
  assert.equal(h.calls[1].replaces, 1);
});

test("a failed save keeps the value and retries; flush reports the failure", async () => {
  const h = harness();
  h.saver.change("a");
  const flushed = h.saver.flush();
  h.calls[0].resolve({ kind: "retry", error: "offline" });
  assert.equal(await flushed, false);
  assert.equal(h.states.at(-1)?.status, "retrying");
  assert.equal(h.states.at(-1)?.pending, true);
  h.fire();
  assert.deepEqual(h.calls.map((c) => c.value), ["a", "a"]);
  h.calls[1].resolve({ kind: "saved", revision: 1 });
  await h.tick();
  assert.equal(h.states.at(-1)?.status, "saved");
});

test("flush sends at once and resolves when the latest value is confirmed", async () => {
  const h = harness({ revision: 4 });
  h.saver.change("a");
  const flushed = h.saver.flush();
  assert.equal(h.timers.size, 0);
  h.saver.change("b");
  h.calls[0].resolve({ kind: "saved", revision: 5 });
  await h.tick();
  assert.equal(h.calls[1].value, "b", "the newer value goes out before flush resolves");
  h.calls[1].resolve({ kind: "saved", revision: 6 });
  assert.equal(await flushed, true);
  assert.equal(h.saver.revision, 6);
});

test("a missing stored draft starts a new draft id with the same answers", async () => {
  const h = harness({ revision: 2 });
  h.saver.change("a");
  h.fire();
  h.calls[0].resolve({ kind: "restart" });
  await h.tick();
  assert.deepEqual([h.calls[1].draftId, h.calls[1].replaces, h.calls[1].value], ["new-1", null, "a"]);
});

test("a conflict stops saving, keeps this tab's value, and resumes on the stored draft", async () => {
  const h = harness({ revision: 1 });
  h.saver.change("mine");
  h.fire();
  const draft = { draftId: "d1", revision: 3, judgmentSha256: "j", basedOn: "judge" as const, basedOnReadingSha256: "j", updatedAt: "", verdicts: {}, evidence: {} };
  h.calls[0].resolve({ kind: "conflict", draft });
  await h.tick();
  assert.equal(h.problems[0].kind, "conflict");
  assert.equal(h.states.at(-1)?.status, "stopped");
  h.saver.change("mine 2");
  assert.equal(h.timers.size, 0, "no autosave while the conflict is open");
  h.saver.resume("d1", 3, true);
  assert.deepEqual([h.calls[1].replaces, h.calls[1].value], [3, "mine 2"]);
});

const DRAFT = { draftId: "d1", revision: 3, judgmentSha256: "j", basedOn: "judge" as const, basedOnReadingSha256: "j", updatedAt: "", verdicts: {}, evidence: {} };

test("keeping this tab's answers after a conflict reports saved only once the project confirms them", async () => {
  const h = harness({ revision: 1 });
  h.saver.change("mine");
  h.fire();
  h.calls[0].resolve({ kind: "conflict", draft: DRAFT });
  await h.tick();
  const before = h.states.length;
  h.saver.change("mine");
  h.saver.resume("d1", 3, true);
  assert.ok(h.states.slice(before).every((s) => s.status !== "saved"), "no saved state before the save is confirmed");
  assert.deepEqual(h.saved, []);
  h.calls[1].resolve({ kind: "retry", error: "offline" });
  await h.tick();
  assert.deepEqual(h.saved, [], "a failed save never marks the answers saved");
  h.fire();
  h.calls[2].resolve({ kind: "saved", revision: 4 });
  await h.tick();
  assert.deepEqual(h.saved, [["mine", "d1", 4]]);
});

test("loading the other tab's answers reports saved without claiming this tab's answers were saved", async () => {
  const h = harness({ revision: 1 });
  h.saver.change("mine");
  h.fire();
  h.calls[0].resolve({ kind: "conflict", draft: DRAFT });
  await h.tick();
  h.saver.resume("d1", 3, false);
  assert.equal(h.states.at(-1)?.status, "saved");
  assert.deepEqual(h.saved, []);
  assert.equal(h.calls.length, 1);
});

test("resolving a conflict clears the conflict message either way", async () => {
  for (const keep of [true, false]) {
    const h = harness({ revision: 1 });
    h.saver.change("mine");
    h.fire();
    h.calls[0].resolve({ kind: "conflict", draft: DRAFT });
    await h.tick();
    assert.equal(h.states.at(-1)?.error, "This review was also saved from another tab or window.");
    h.saver.resume("d1", 3, keep);
    assert.equal(h.states.at(-1)?.error, null, keep ? "keep this tab's answers" : "load the other tab's answers");
  }
});

test("the last error stays in the state until a save is confirmed", async () => {
  const h = harness();
  h.saver.change("a");
  h.fire();
  h.calls[0].resolve({ kind: "retry", error: "The project is busy." });
  await h.tick();
  assert.deepEqual([h.states.at(-1)?.status, h.states.at(-1)?.error], ["retrying", "The project is busy."]);
  h.fire();
  h.calls[1].resolve({ kind: "saved", revision: 1 });
  await h.tick();
  assert.equal(h.states.at(-1)?.error, null);
  h.saver.change("b");
  h.fire();
  h.calls[2].resolve({ kind: "refused", error: JUDGMENT_NOT_CURRENT });
  await h.tick();
  assert.deepEqual([h.states.at(-1)?.status, h.states.at(-1)?.error], ["stopped", JUDGMENT_NOT_CURRENT]);
  assert.equal(h.timers.size, 0, "a refusal is not retried");
});

test("save responses that cannot succeed on retry are refusals", () => {
  assert.deepEqual(classifySave(409, { error: JUDGMENT_NOT_CURRENT }), { kind: "refused", error: JUDGMENT_NOT_CURRENT });
  assert.deepEqual(classifySave(409, { error: BASE_NOT_ON_RECORD }), { kind: "refused", error: BASE_NOT_ON_RECORD });
  assert.deepEqual(classifySave(409, { error: JUDGMENT_CHANGED }), { kind: "refused", error: JUDGMENT_CHANGED });
  assert.deepEqual(classifySave(409, { error: REVIEW_ALREADY_FINISHED }), { kind: "restart" });
  assert.deepEqual(classifySave(409, { error: "x", draft: null }), { kind: "restart" });
  assert.equal(classifySave(409, { error: "x", draft: DRAFT }).kind, "conflict");
  assert.deepEqual(classifySave(409, { error: "Project changed. Try again." }), { kind: "retry", error: "Project changed. Try again." });
  assert.deepEqual(classifySave(503, {}), { kind: "retry", error: "HTTP 503" });
  assert.deepEqual(classifySave(400, { error: "Invalid reviewer ID." }), { kind: "refused", error: "Invalid reviewer ID." });
  assert.deepEqual(classifySave(200, { revision: 2 }), { kind: "saved", revision: 2 });
});

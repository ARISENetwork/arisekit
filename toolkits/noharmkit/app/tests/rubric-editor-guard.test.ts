import assert from "node:assert/strict";
import { test } from "node:test";

import { guardRubricHistory, isLeavingRubricLink, saveRubricBeforeLeaving, type RubricEditorController } from "../lib/rubric-editor-guard";

test("save-and-continue awaits a successful save, keeps dirty state on failure, and never saves ineligible editors", async () => {
  let finish!: (saved: boolean) => void;
  let completed = false;
  const pending: RubricEditorController = { dirty: true, saving: false, canSave: true, error: null, save: () => new Promise((resolve) => { finish = resolve; }) };
  const saving = saveRubricBeforeLeaving(pending).then((saved) => { completed = saved; });
  await Promise.resolve();
  assert.equal(completed, false);
  finish(true);
  await saving;
  assert.equal(completed, true);

  const failing: RubricEditorController = { dirty: true, saving: false, canSave: true, error: "Source changed.", save: async () => false };
  assert.equal(await saveRubricBeforeLeaving(failing), false);
  assert.equal(failing.dirty, true);
  assert.equal(failing.error, "Source changed.");
  failing.save = async () => true;
  assert.equal(await saveRubricBeforeLeaving(failing), true);

  let calls = 0;
  const ineligible: RubricEditorController = { dirty: true, saving: false, canSave: false, error: null, save: async () => { calls += 1; return true; } };
  assert.equal(await saveRubricBeforeLeaving(null), false);
  assert.equal(await saveRubricBeforeLeaving(ineligible), false);
  assert.equal(await saveRubricBeforeLeaving({ ...ineligible, saving: true, canSave: true }), false);
  assert.equal(await saveRubricBeforeLeaving({ ...ineligible, dirty: false, canSave: true }), true);
  assert.equal(calls, 0);
});

test("case, rubric version, sidebar, and project destinations leave the current editor", () => {
  const current = "http://localhost:5190/noharm/rubrics?case=A&version=run1";
  for (const destination of ["?case=B&version=run1", "?case=A&version=run2", "/noharm/responses", "/noharm/welcome", "https://example.org/"]) {
    assert.equal(isLeavingRubricLink(destination, current, "", false), true, destination);
  }
  for (const destination of [current, "#D1", "mailto:reviewer@example.org"]) {
    assert.equal(isLeavingRubricLink(destination, current, "", false), false, destination);
  }
  assert.equal(isLeavingRubricLink("/noharm/responses", current, "_blank", false), false);
  assert.equal(isLeavingRubricLink("/noharm/responses", current, "", true), false);
});

test("the history guard blocks only eligible same-document Back while mounted", () => {
  const traversals: string[] = [];
  const navigation = Object.assign(new EventTarget(), { traverseTo: (key: string): void => { traversals.push(key); } });
  let approval: (() => void) | undefined;
  const remove = guardRubricHistory(navigation, () => "http://localhost/noharm/rubrics?version=run2", () => true, (action) => { approval = action; });
  const back = (): Event => Object.assign(new Event("navigate", { cancelable: true }), { navigationType: "traverse", destination: { key: "run1-entry", url: "http://localhost/noharm/rubrics?version=run1", sameDocument: true } });
  const attempt = back();
  navigation.dispatchEvent(attempt);
  assert.equal(attempt.defaultPrevented, true);
  assert.deepEqual(traversals, []);
  assert.ok(approval);
  remove();
  approval();
  assert.deepEqual(traversals, ["run1-entry"]);
  const afterUnmount = back();
  navigation.dispatchEvent(afterUnmount);
  assert.equal(afterUnmount.defaultPrevented, false);

  let prompted = false;
  const clean = Object.assign(new EventTarget(), { traverseTo: (): void => {} });
  const removeClean = guardRubricHistory(clean, () => "http://localhost/noharm/rubrics", () => false, () => { prompted = true; });
  const cleanAttempt = Object.assign(new Event("navigate", { cancelable: true }), { navigationType: "traverse", destination: { key: "prior", url: "http://localhost/noharm/dataset", sameDocument: true } });
  clean.dispatchEvent(cleanAttempt);
  assert.equal(cleanAttempt.defaultPrevented, false);
  assert.equal(prompted, false);
  removeClean();
  const removeDirty = guardRubricHistory(clean, () => "http://localhost/noharm/rubrics", () => true, () => { prompted = true; });
  for (const [sameDocument, cancelable] of [[false, true], [true, false]]) {
    const documentExit = Object.assign(new Event("navigate", { cancelable }), { navigationType: "traverse", destination: { key: "prior", url: "http://localhost/noharm/dataset", sameDocument } });
    clean.dispatchEvent(documentExit);
    assert.equal(documentExit.defaultPrevented, false);
    assert.equal(prompted, false);
  }
  removeDirty();
  assert.doesNotThrow(() => guardRubricHistory(undefined, () => "", () => true, () => {})());
});

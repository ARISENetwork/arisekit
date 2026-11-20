import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { FailedErrors, FailedTag } from "../components/runs/VersionFailure";
import { newTiming } from "../lib/answer-table";
import { httpStatus, loadEditorPayload, saveReviewedTable, ValidationError } from "../lib/caseset/editor";
import { loadBenchmark } from "../lib/caseset/metrics";
import { resolveStepParams } from "../lib/caseset/routes";
import { NotFoundError } from "../lib/caseset/paths";
import { editorNeedsBanner } from "../lib/caseset/provisional";
import { listCasesets, loadCasePage, loadLens } from "../lib/caseset/read";
import { tableSha256 } from "../lib/caseset/hash";
import { addReviewed, buildFixture, CASESET, MODEL_A, REVIEWED_FILE, TABLE, writeCasesetFile } from "./caseset-fixture";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const AutogradingStep: typeof import("../components/mc/steps/AutogradingStep").default = require("../components/mc/steps/AutogradingStep").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const summary = (f: ReturnType<typeof buildFixture>) => listCasesets(f.root).find((c) => c.name === CASESET);
const page = (f: ReturnType<typeof buildFixture>) => loadCasePage(f.root, CASESET, "Test002");
const banner = (f: ReturnType<typeof buildFixture>, version: string): boolean => editorNeedsBanner(page(f), version);

test("provisional banner on index and editor", () => {
  const f = buildFixture();
  addReviewed(f);
  // The index keeps the banner when a reviewed copy exists but responses were judged against run1.
  assert.equal(summary(f)?.clinicianReviewed, true);
  assert.equal(summary(f)?.provisional, true);
  // The editor shows the banner unless the opened version is a passing reviewed copy.
  assert.equal(banner(f, "run1"), true);
  assert.equal(banner(f, "run2"), true);
  assert.equal(banner(f, "run3"), true);
  assert.equal(banner(f, "reviewed-dwu"), false);
  // The index drops the banner only when every judged response used a passing reviewed table.
  const reviewedSha = tableSha256(TABLE);
  for (const model of ["openrouter-test-model-a", "openrouter-test-model-b"]) {
    const file = path.join(f.dir, "results", "judge", `${model}.jsonl`);
    const rows = readFileSync(file, "utf8").trim().split("\n").map((l) => ({ ...JSON.parse(l), rubric: "reviewed-dwu", rubric_sha256: reviewedSha }));
    writeFileSync(file, rows.map((r) => `${JSON.stringify(r)}\n`).join(""));
  }
  assert.equal(summary(f)?.provisional, false);
  const failed = buildFixture();
  addReviewed(failed, "failed");
  assert.equal(banner(failed, "reviewed-dwu"), true);
});

const oddTable = { ...TABLE, decisions: [{ ...TABLE.decisions[0], recommendations: [{ ...TABLE.decisions[0].recommendations[0], score: 7.5 }] }, TABLE.decisions[1]] };

test("versions that cannot hash", () => {
  // Every version of the plain fixture can be the basis of a reviewed copy, and saving from failed run2 still works.
  const normal = buildFixture();
  for (const version of ["run1", "run2", "run3"]) {
    const payload = loadEditorPayload(normal.root, CASESET, "Test002", version, "dw");
    assert.equal(payload.canSave, true, version);
    assert.equal(payload.cannotSaveReason, undefined, version);
  }
  const fixed = { ...TABLE, usualCare: { harm: "moderate" as const } };
  const req = { root: normal.root, caseset: CASESET, caseId: "Test002", version: "run2", reviewer: "dw", record: fixed, timing: newTiming(new Date("2026-09-28T22:00:00Z")) };
  assert.equal(saveReviewedTable(req).version, "reviewed-dw");
  const saved = JSON.parse(readFileSync(path.join(normal.dir, "answer-tables", "Test002.reviewed-dw.json"), "utf8"));
  assert.equal(saved.basedOn.version, "run2");
  assert.match(saved.basedOn.sha256, /^[0-9a-f]{64}$/);

  // A failed run with a non-integer score does not break the case page and reads as failed with no hash.
  const odd = buildFixture();
  writeCasesetFile(odd, "answer-tables/Test002.run2.json", oddTable);
  const loaded = page(odd);
  const run2 = loaded.tables.find((t) => t.version === "run2");
  assert.equal(run2?.status, "failed");
  assert.equal(run2?.sha256, null);
  assert.equal(run2?.record?.decisions[0].recommendations[0].score, 7.5);
  assert.equal(loaded.tables.find((t) => t.version === "run1")?.sha256, tableSha256(TABLE));
  // The editor payload says up front that it cannot be the basis of a reviewed copy, and a save is refused with 422.
  const blocked = loadEditorPayload(odd.root, CASESET, "Test002", "run2", "dw");
  assert.equal(blocked.canSave, false);
  assert.match(blocked.cannotSaveReason ?? "", /^This version cannot be the basis of a reviewed copy: .*only safe integers.* Open another version\.$/);
  assert.throws(
    () => saveReviewedTable({ ...req, root: odd.root }),
    (error: unknown) => error instanceof ValidationError && httpStatus(error) === 422 && /run2/.test(error.message),
  );
  assert.throws(() => readFileSync(path.join(odd.dir, "answer-tables", "Test002.reviewed-dw.json")));
  assert.equal(loadEditorPayload(odd.root, CASESET, "Test002", "run2", "dw").status, "failed");

  // Re-saving your own reviewed copy never needs a hash, so it stays savable.
  const own = buildFixture();
  addReviewed(own, "failed");
  writeCasesetFile(own, "answer-tables/Test002.reviewed-dwu.json", { ...REVIEWED_FILE, record: oddTable });
  assert.equal(loadEditorPayload(own.root, CASESET, "Test002", "reviewed-dwu", "dwu").canSave, true);
  assert.equal(loadEditorPayload(own.root, CASESET, "Test002", "reviewed-dwu", "other").canSave, false);
});

test("the judge command names the judgment's rubric, else a passing reviewed table, else the first passing run, else a placeholder", () => {
  const rubricOf = (command: string): string => /--rubric (\S+)$/.exec(command)?.[1] ?? "";

  const recorded = buildFixture();
  addReviewed(recorded);
  const withRecord = page(recorded);
  assert.equal(rubricOf(withRecord.commands.judge), "run1");
  assert.equal(rubricOf(withRecord.responses.find((r) => r.judge === "stale")?.judgeCommand ?? ""), "run1");

  const reviewed = buildFixture();
  rmSync(path.join(reviewed.dir, "results", "judge"), { recursive: true });
  addReviewed(reviewed);
  const notRun = page(reviewed);
  assert.equal(rubricOf(notRun.commands.judge), "reviewed-dwu");
  assert.equal(rubricOf(notRun.responses[0].judgeCommand), "reviewed-dwu");

  const lens = loadLens(reviewed.root, CASESET, "Test002", MODEL_A, "1");
  assert.equal(rubricOf(lens.row.judgeCommand), "reviewed-dwu");
  const bench = loadBenchmark(reviewed.root, CASESET);
  const params = resolveStepParams(bench, { model: MODEL_A });
  assert.ok(params);
  const output = renderToStaticMarkup(AutogradingStep({ bench, params }).props.outputs);
  assert.match(output, /Not autograded yet/);
  assert.match(output, /Run autograding for item Test002 in the cs1 project/);

  const run = buildFixture();
  rmSync(path.join(run.dir, "results", "judge"), { recursive: true });
  assert.equal(rubricOf(page(run).commands.judge), "run1");

  const none = buildFixture();
  rmSync(path.join(none.dir, "results", "judge"), { recursive: true });
  writeCasesetFile(none, "answer-tables/Test002.run1.status.json", { status: "failed", errors: ["x"] });
  writeCasesetFile(none, "answer-tables/Test002.run3.status.json", { status: "failed", errors: ["x"] });
  assert.equal(rubricOf(page(none).commands.judge), "<version>");
});

test("committee ratings are dropped when the run failed or the table changed since they were made", () => {
  const f = buildFixture();
  assert.equal(page(f).tables.find((t) => t.version === "run1")?.ratings?.usualCare?.median, "moderate");

  const changed = buildFixture();
  const ratings = JSON.parse(readFileSync(path.join(changed.dir, "answer-tables", "Test002.run1.ratings.json"), "utf8"));
  writeCasesetFile(changed, "answer-tables/Test002.run1.ratings.json", { ...ratings, table_sha256: "0".repeat(64) });
  assert.equal(page(changed).tables.find((t) => t.version === "run1")?.ratings, null);

  const failed = buildFixture();
  writeCasesetFile(failed, "answer-tables/Test002.run1.ratings.json", { ...ratings, status: "failed", errors: ["quorum"] });
  assert.equal(page(failed).tables.find((t) => t.version === "run1")?.ratings, null);
  assert.equal(loadEditorPayload(failed.root, CASESET, "Test002", "run1", "dw").ratings, null);
});

test("save and load errors map to honest HTTP statuses", () => {
  assert.equal(httpStatus(new NotFoundError("x")), 404);
  assert.equal(httpStatus(new ValidationError(["x"])), 422);
  assert.equal(httpStatus(new Error("Invalid reviewer ID.")), 400);
  assert.equal(httpStatus(Object.assign(new Error("EACCES: permission denied"), { code: "EACCES" })), 500);
  assert.equal(httpStatus(Object.assign(new Error("ENOSPC: no space left"), { code: "ENOSPC" })), 500);
  assert.equal(httpStatus(new SyntaxError("Unexpected token")), 400);
});

const editor = readFileSync(path.join(process.cwd(), "components", "AnswerTableEditor.tsx"), "utf8");

test("FailedTag and FailedErrors render, and a version that cannot be saved from disables Save with its reason", () => {
  assert.match(renderToStaticMarkup(createElement(FailedTag)), />Failed<\/span>/);
  const list = renderToStaticMarkup(createElement(FailedErrors, { errors: ["validator: Usual care: rate its harm.", "second"] }));
  assert.match(list, /validator: Usual care: rate its harm\./);
  assert.match(list, /<li[^>]*>second<\/li>/);
  const failedBlock = renderToStaticMarkup(createElement(FailedErrors, { errors: ["e1"], reason: "This version cannot be the basis of a reviewed copy: x. Open another version." }));
  assert.match(failedBlock, /This version cannot be the basis of a reviewed copy: x\. Open another version\./);
  const neutral = renderToStaticMarkup(createElement(FailedErrors, { errors: ["e1"] }));
  assert.match(neutral, /This version failed validation\. Fix the errors before saving\./);
  assert.doesNotMatch(neutral, /create your reviewed copy/);
  assert.doesNotMatch(neutral, /cannot be the basis/);
  const f = buildFixture();
  const payload = loadEditorPayload(f.root, CASESET, "Test002", "run2", "dw");
  assert.deepEqual([payload.status, payload.errors], ["failed", ["validator: Usual care: rate its harm."]]);
  // loaded.canSave === false disables Save and passes the reason to FailedErrors.
  assert.match(editor, /const canSave = Boolean\(!previewOnly && loaded && reviewerId && timing\.current && !saving && errors\.length === 0 && loaded\.canSave !== false\);/);
  assert.match(editor, /disabled=\{!canSave\}/);
  assert.match(editor, /<FailedErrors errors=\{loaded\.errors \?\? \[\]\} reason=\{loaded\.canSave === false \? loaded\.cannotSaveReason : undefined\} \/>/);
});

test("a failed save keeps unsaved edits guarded: the unload warning follows a dirty flag, not the save status", () => {
  assert.match(editor, /const \[dirty, setDirty\] = useState\(false\);/);
  assert.match(editor, /if \(dirty\) event\.preventDefault\(\);/);
  assert.match(editor, /\}, \[dirty\]\);/);
  assert.doesNotMatch(editor, /status === "dirty"\) event\.preventDefault/);
  assert.equal((editor.match(/setStatus\("dirty"\)/g) ?? []).length, 1, "edits go through one markDirty");
  assert.match(editor, /if \(!response\.ok\) throw new Error\(body\.error\);/);
  const failedSave = /catch \(error\) \{\s*setStatus\("error"\);[\s\S]*?return false;\s*\}/.exec(editor)?.[0] ?? "";
  assert.ok(failedSave && !failedSave.includes("setDirty(false)"), "a failed save must not clear the dirty flag");
  assert.match(editor, /setStatus\(savedLatest \? "saved" : "dirty"\);\s*setDirty\(!savedLatest\);/);
});

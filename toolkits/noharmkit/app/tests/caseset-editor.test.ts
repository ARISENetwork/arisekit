import assert from "node:assert/strict";
import { chmodSync, existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, readlinkSync, renameSync, symlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { newTiming, validateAnswerTable } from "../lib/answer-table";
import type { AnswerTableCase } from "../lib/answer-table";
import { ConflictError, httpStatus, loadEditorPayload, saveReviewedTable, ValidationError } from "../lib/caseset/editor";
import { tableSha256 } from "../lib/caseset/hash";
import { listVersionLabels, NotFoundError } from "../lib/caseset/paths";
import { loadTableVersion } from "../lib/caseset/read";
import { readReviews } from "../lib/caseset/reviews";
import { eachCase } from "./cases";
import { buildFixture, CASESET, relink, TABLE, writeCasesetFile } from "./caseset-fixture";
import type { Fixture } from "./caseset-fixture";

const NOW = new Date("2026-09-28T12:00:00.000Z");
const timing = newTiming(NOW);
const edited: AnswerTableCase = { ...TABLE, decisions: TABLE.decisions.map((d) => (d.id === "D2" ? { ...d, question: "Should apixaban start now?" } : d)) };
const reviewedFile = (dir: string): string => path.join(dir, "answer-tables", "Test002.reviewed-dw.json");

test("generated ratings, tags, timing and relationships reach the editor unchanged", () => {
  const fixture = buildFixture();
  const record: AnswerTableCase = {
    ...TABLE,
    usualCare: { harm: "severe" },
    decisions: [
      { ...TABLE.decisions[0], harmIfNotAddressedOverride: "moderate", harmIfDelayedOverride: "mild",
        recommendations: [{ ...TABLE.decisions[0].recommendations[0], tags: ["followUp"],
          equivalents: ["Arrange specialist reassessment."], parts: ["Arrange a referral.", "Reassess symptoms."],
          alsoTakesCareOf: ["D2"] }] },
      { ...TABLE.decisions[1], activation: { type: "onlyIf", rows: ["D1.O1"], match: "all" },
        recommendations: [
          { ...TABLE.decisions[1].recommendations[0], tags: ["medication"], drugClass: "Anticoagulant" },
          { ...TABLE.decisions[1].recommendations[1], tags: ["medication"], harmIfRecommendedOverride: "severe" },
          { id: "D2.O3", text: "No additional treatment.", score: 7, tags: ["none", "medication"], relativeHarmOverride: "none" },
        ] },
    ],
  };
  assert.deepEqual(validateAnswerTable(record), []);
  writeCasesetFile(fixture, "answer-tables/Test002.run3.json", record);
  const payload = loadEditorPayload(fixture.root, CASESET, "Test002", "run3", "dw");
  assert.equal(payload.version, "run3");
  assert.equal(payload.status, "pass");
  assert.deepEqual(payload.record, record);
  assert.equal(payload.sourceSha256, tableSha256(record));
  saveReviewedTable({ root: fixture.root, caseset: CASESET, caseId: "Test002", version: "run3", reviewer: "dw", record, timing, now: NOW });
  const saved = loadEditorPayload(fixture.root, CASESET, "Test002", "reviewed-dw", "dw");
  assert.deepEqual(saved.record, record);
  assert.deepEqual(loadTableVersion(fixture.dir, "Test002", "run3").record, record);
});

test("save from run1 writes reviewed copy, status and review record; re-save keeps the first basis", () => {
  const { root, dir } = buildFixture();
  const runFile = path.join(dir, "answer-tables", "Test002.run1.json");
  const before = readFileSync(runFile, "utf8");
  const result = saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: edited, timing, now: NOW });
  assert.deepEqual(result, { savedAt: NOW.toISOString(), version: "reviewed-dw", contentSha256: tableSha256(edited) });
  assert.equal(readFileSync(runFile, "utf8"), before);
  assert.deepEqual(JSON.parse(readFileSync(reviewedFile(dir), "utf8")), {
    record: edited, basedOn: { version: "run1", sha256: tableSha256(TABLE) }, reviewer: "dw", timing, savedAt: NOW.toISOString(),
  });
  assert.deepEqual(JSON.parse(readFileSync(path.join(dir, "answer-tables", "Test002.reviewed-dw.status.json"), "utf8")), { status: "pass", errors: [], savedAt: NOW.toISOString() });
  // The save appends a review record bound to the saved content and its basis.
  assert.deepEqual(readReviews(dir), [{
    step: "rubrics", caseId: "Test002", item: "reviewed-dw", contentSha256: tableSha256(edited), basedOnSha256: tableSha256(TABLE), reviewer: "dw", reviewedAt: NOW.toISOString(),
  }]);

  // Re-saving a reviewed copy keeps its first basis, and the source run is never written.
  const again = buildFixture();
  const sourceBefore = readFileSync(path.join(again.dir, "answer-tables", "Test002.run3.json"), "utf8");
  saveReviewedTable({ root: again.root, caseset: CASESET, caseId: "Test002", version: "run3", reviewer: "dw", record: edited, timing, now: NOW });
  saveReviewedTable({ root: again.root, caseset: CASESET, caseId: "Test002", version: "reviewed-dw", reviewer: "dw", record: TABLE, timing, now: NOW });
  const saved = JSON.parse(readFileSync(reviewedFile(again.dir), "utf8"));
  assert.equal(saved.basedOn.version, "run3");
  assert.deepEqual(saved.record, TABLE);
  assert.equal(readFileSync(path.join(again.dir, "answer-tables", "Test002.run3.json"), "utf8"), sourceBefore);
});

test("Reset loads the rubric a reviewed copy was based on, keeping the copy's hashes so the next save replaces it", () => {
  const { root } = buildFixture();
  saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: edited, timing, now: NOW });
  const copy = loadEditorPayload(root, CASESET, "Test002", "reviewed-dw", "dw");
  const original = loadEditorPayload(root, CASESET, "Test002", "reviewed-dw", "dw", true);
  assert.deepEqual(copy.record, edited);
  assert.deepEqual(original.record, TABLE);
  assert.equal(original.version, "reviewed-dw");
  assert.equal(original.fromCopy, true);
  assert.equal(original.sourceSha256, copy.sourceSha256);
  saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "reviewed-dw", reviewer: "dw", record: original.record, timing, sourceSha256: original.sourceSha256 ?? undefined, now: NOW });
  assert.deepEqual(loadEditorPayload(root, CASESET, "Test002", "reviewed-dw", "dw").record, TABLE);
  // Any other version is already the original.
  assert.deepEqual(loadEditorPayload(root, CASESET, "Test002", "run1", "dw", true), loadEditorPayload(root, CASESET, "Test002", "run1", "dw"));
});

test("an invalid table is refused with its validator errors and nothing is written", () => {
  const { root, dir } = buildFixture();
  const bad: AnswerTableCase = { ...TABLE, usualCare: { harm: null } };
  assert.throws(
    () => saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: bad, timing, now: NOW }),
    (error: unknown) => error instanceof ValidationError && error.errors.includes("Usual care: rate its harm.") && httpStatus(error) === 422,
  );
  assert.equal(existsSync(reviewedFile(dir)), false);
  assert.equal(existsSync(path.join(dir, "answer-tables", "Test002.reviewed-dw.status.json")), false);
});

test("saves refuse unsafe or unknown identifiers and write nothing outside the caseset", () => {
  const { root, dir, outside } = buildFixture();
  const ok = { root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: edited, timing, now: NOW };
  assert.throws(() => saveReviewedTable({ ...ok, caseset: "../outside" }), NotFoundError);
  assert.throws(() => saveReviewedTable({ ...ok, caseset: "linked" }), NotFoundError);
  assert.throws(() => saveReviewedTable({ ...ok, caseId: "../outside", record: { ...edited, caseId: "../outside" } }), NotFoundError);
  assert.throws(() => saveReviewedTable({ ...ok, version: "../../outside" }), NotFoundError);
  assert.throws(() => saveReviewedTable({ ...ok, version: "run9" }), NotFoundError);
  assert.throws(() => saveReviewedTable({ ...ok, reviewer: "../dw" }), /Invalid reviewer ID/);
  assert.throws(() => saveReviewedTable({ ...ok, record: { ...edited, caseId: "Test003" } }), /does not match/);
  assert.equal(existsSync(path.join(outside, "answer-tables")), false);
  assert.equal(existsSync(reviewedFile(dir)), false);
});

test("editor payload before and after the first save", () => {
  const { root } = buildFixture();
  const run1 = loadEditorPayload(root, CASESET, "Test002", "run1", "dw");
  assert.equal(run1.ratings?.decisions.D2.disagreement, true);
  assert.equal(run1.fromCopy, false);
  assert.equal(run1.notice, "Opened run1. Saving creates reviewed-dw; run1 is not changed.");
  assert.equal(run1.sourceSha256, tableSha256(TABLE));
  assert.equal(run1.replacesSha256, null);
  assert.equal(loadEditorPayload(root, CASESET, "Test002", "run2", "dw").status, "failed");
  saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: edited, timing, now: NOW });
  assert.equal(loadEditorPayload(root, CASESET, "Test002", "run3", "dw").notice, "Opened run3. Saving replaces your reviewed copy (reviewed-dw).");
  assert.equal(loadEditorPayload(root, CASESET, "Test002", "run1", "dw").replacesSha256, tableSha256(edited));
  const own = loadEditorPayload(root, CASESET, "Test002", "reviewed-dw", "dw");
  assert.equal(own.fromCopy, true);
  assert.deepEqual(own.timing, timing);
  assert.equal(own.notice, "Your reviewed copy, based on run1");
  assert.equal(own.sourceSha256, tableSha256(edited));
  assert.throws(() => loadEditorPayload(root, CASESET, "Test002", "run1", "BAD"), /Invalid reviewer ID/);
});

// A link planted at any path a save writes must never be followed, whether it points outside the caseset or at a sibling generated file.
// tablesRemain: the plant leaves the real answer-tables folder in place, so its runs still load.
// The folder-link refusal names the resolved caseset path, so only the other plants check the message hides the root.
type Plant = { name: string; version: "run1" | "run3"; plant: (f: Fixture) => string; tablesRemain: boolean };
const tablesDir = (f: Fixture): string => path.join(f.dir, "answer-tables");
const PLANTS: Plant[] = [
  { name: "answer-tables folder linked outside", version: "run3", tablesRemain: false, plant: (f) => {
    mkdirSync(path.join(f.outside, "tables"));
    relink(path.join(f.outside, "tables"), tablesDir(f));
    return tablesDir(f);
  } },
  { name: "dangling reviewed file to outside", version: "run3", tablesRemain: true, plant: (f) => {
    symlinkSync(path.join(f.outside, "planted.json"), reviewedFile(f.dir));
    return reviewedFile(f.dir);
  } },
  { name: "status file to an outside victim", version: "run3", tablesRemain: true, plant: (f) => {
    const link = path.join(tablesDir(f), "Test002.reviewed-dw.status.json");
    symlinkSync(path.join(f.outside, "cases", "Test002.json"), link);
    return link;
  } },
  { name: "temporary file to an outside victim", version: "run1", tablesRemain: true, plant: (f) => {
    const link = path.join(tablesDir(f), "Test002.reviewed-dw.json.tmp");
    symlinkSync(path.join(f.outside, "cases", "Test002.json"), link);
    return link;
  } },
  { name: "status file to the sibling failed run2 status", version: "run3", tablesRemain: true, plant: (f) => {
    const link = path.join(tablesDir(f), "Test002.reviewed-dw.status.json");
    symlinkSync("Test002.run2.status.json", link);
    return link;
  } },
  { name: "temporary file to the sibling run1", version: "run3", tablesRemain: true, plant: (f) => {
    const link = path.join(tablesDir(f), "Test002.reviewed-dw.json.tmp");
    symlinkSync("Test002.run1.json", link);
    return link;
  } },
  { name: "reviewed file to the sibling run1", version: "run3", tablesRemain: true, plant: (f) => {
    symlinkSync("Test002.run1.json", reviewedFile(f.dir));
    return reviewedFile(f.dir);
  } },
];

// Every entry under `dir`, without following links: file bytes, link targets, and folders.
function snapshot(dir: string, skip: string): Map<string, string> {
  const entries = new Map<string, string>();
  const walk = (current: string): void => {
    for (const name of readdirSync(current)) {
      const file = path.join(current, name);
      if (file === skip) continue;
      const stat = lstatSync(file);
      if (stat.isSymbolicLink()) entries.set(file, `link ${readlinkSync(file)}`);
      else if (stat.isDirectory()) { entries.set(file, "folder"); walk(file); }
      else entries.set(file, readFileSync(file).toString("hex"));
    }
  };
  walk(dir);
  return entries;
}

test("a link planted at any save path is refused and nothing it points to changes", () => eachCase(PLANTS, (c) => c.name, (c) => {
  const f = buildFixture();
  const planted = c.plant(f);
  const before = [snapshot(f.outside, planted), snapshot(f.dir, planted)];
  assert.throws(
    () => saveReviewedTable({ root: f.root, caseset: CASESET, caseId: "Test002", version: c.version, reviewer: "dw", record: edited, timing, now: NOW }),
    (error: unknown) => error instanceof NotFoundError && httpStatus(error) === 404 && (!c.tablesRemain || !error.message.includes(f.root)),
  );
  assert.deepEqual([snapshot(f.outside, planted), snapshot(f.dir, planted)], before);
  // Nothing was written: each reviewed entry is absent, or still the planted link and not a regular file.
  for (const file of [reviewedFile(f.dir), path.join(tablesDir(f), "Test002.reviewed-dw.status.json")]) assert.notEqual(lstatSync(file, { throwIfNoEntry: false })?.isFile(), true);
  if (c.tablesRemain) {
    assert.equal(loadTableVersion(f.dir, "Test002", "run2").status, "failed");
    assert.deepEqual(loadTableVersion(f.dir, "Test002", "run1").record, TABLE);
  }
}));

test("a save is refused with 409 when the opened version changed on disk, and nothing is written", () => {
  const { root, dir } = buildFixture();
  const opened = loadEditorPayload(root, CASESET, "Test002", "run1", "dw");
  writeFileSync(path.join(dir, "answer-tables", "Test002.run1.json"), `${JSON.stringify(edited, null, 2)}\n`);
  assert.throws(
    () => saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: edited, timing, now: NOW, sourceSha256: opened.sourceSha256 ?? undefined, replacesSha256: opened.replacesSha256 }),
    (error: unknown) => error instanceof ConflictError && httpStatus(error) === 409 && /Reload/.test((error as Error).message),
  );
  assert.equal(existsSync(reviewedFile(dir)), false);
  assert.equal(existsSync(path.join(dir, "reviews.jsonl")), false);
});

test("replacesSha256 must match the copy on disk", () => {
  const { root } = buildFixture();
  const opened = loadEditorPayload(root, CASESET, "Test002", "run1", "dw");
  const first = saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: edited, timing, now: NOW, sourceSha256: opened.sourceSha256 ?? undefined, replacesSha256: opened.replacesSha256 });
  // The reviewer's copy changed after the page was opened.
  assert.throws(
    () => saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: TABLE, timing, now: NOW, sourceSha256: opened.sourceSha256 ?? undefined, replacesSha256: opened.replacesSha256 }),
    ConflictError,
  );
  // Saving again with the hashes the last save returned succeeds.
  const second = saveReviewedTable({ root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: TABLE, timing, now: NOW, sourceSha256: opened.sourceSha256 ?? undefined, replacesSha256: first.contentSha256 });
  assert.equal(second.contentSha256, tableSha256(TABLE));
});

test("an unsafe or unwritable review log refuses before replacing the reviewed copy or its status", () => {
  for (const unsafe of ["symlink", "unwritable"] as const) {
    const f = buildFixture();
    const req = { root: f.root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: TABLE, timing, now: NOW };
    saveReviewedTable(req);
    const copy = reviewedFile(f.dir);
    const status = path.join(f.dir, "answer-tables", "Test002.reviewed-dw.status.json");
    const log = path.join(f.dir, "reviews.jsonl");
    const before = [copy, status, log].map((file) => readFileSync(file, "utf8"));
    if (unsafe === "symlink") { renameSync(log, `${log}.original`); symlinkSync(`${log}.original`, log); }
    else chmodSync(log, 0o444);
    try {
      assert.throws(() => saveReviewedTable({ ...req, record: edited }));
      assert.deepEqual([copy, status, log].map((file) => readFileSync(file, "utf8")), before, unsafe);
    } finally {
      if (unsafe === "unwritable") chmodSync(log, 0o644);
    }
  }
});

test("invalid own copies still have conflict identities so repairs cannot overwrite unseen edits", () => {
  const f = buildFixture();
  saveReviewedTable({ root: f.root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: TABLE, timing, now: NOW });
  const bad = { ...TABLE, usualCare: { harm: 7.5 } };
  const file = reviewedFile(f.dir);
  const saved = JSON.parse(readFileSync(file, "utf8"));
  writeFileSync(file, JSON.stringify({ ...saved, record: bad }));
  writeFileSync(path.join(f.dir, "answer-tables", "Test002.reviewed-dw.status.json"), JSON.stringify({ status: "failed", errors: ["invalid draft"] }));
  const payload = loadEditorPayload(f.root, CASESET, "Test002", "reviewed-dw", "dw");
  assert.match(payload.sourceSha256 ?? "", /^[0-9a-f]{64}$/);
  writeFileSync(file, JSON.stringify({ ...saved, record: { ...bad, harmOverrides: false } }));
  assert.throws(() => saveReviewedTable({ root: f.root, caseset: CASESET, caseId: "Test002", version: "reviewed-dw", reviewer: "dw", record: TABLE, timing, sourceSha256: payload.sourceSha256! }), ConflictError);
});

test("replacement history preserves prior table and status as opaque bytes without changing record formats", () => {
  const f = buildFixture();
  const req = { root: f.root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: TABLE, timing, now: NOW };
  saveReviewedTable(req);
  const history = path.join(f.dir, "answer-tables", "history", "Test002.reviewed-dw");
  assert.equal(existsSync(history), false, "An initial save has no prior copy to archive.");
  const table = reviewedFile(f.dir);
  const status = path.join(f.dir, "answer-tables", "Test002.reviewed-dw.status.json");
  const opaque = [Buffer.from([0, 0xff, 13, 10, 32]), Buffer.from("unknown status format\r\n")];
  writeFileSync(table, opaque[0]);
  writeFileSync(status, opaque[1]);
  saveReviewedTable({ ...req, record: edited });
  const first = readdirSync(history);
  assert.equal(first.length, 1);
  const archived = ["Test002.reviewed-dw.json", "Test002.reviewed-dw.status.json"].map((name) => readFileSync(path.join(history, first[0], name)));
  assert.deepEqual(archived, opaque);
  const current = [table, status].map((file) => readFileSync(file));
  // Replacement staging preserves an earlier regular temporary file.
  const oldTemporary = `${table}.tmp`;
  writeFileSync(oldTemporary, "prior incomplete attempt");
  saveReviewedTable(req);
  assert.equal(readFileSync(oldTemporary, "utf8"), "prior incomplete attempt");
  assert.equal(readdirSync(path.join(f.dir, "answer-tables")).filter((file) => file.endsWith(".tmp")).length, 1);
  const snapshots = readdirSync(history);
  assert.equal(snapshots.length, 2);
  assert.deepEqual(["Test002.reviewed-dw.json", "Test002.reviewed-dw.status.json"].map((name) => readFileSync(path.join(history, first[0], name))), opaque, "Later saves never overwrite existing history.");
  const second = snapshots.find((name) => name !== first[0])!;
  assert.deepEqual(["Test002.reviewed-dw.json", "Test002.reviewed-dw.status.json"].map((name) => readFileSync(path.join(history, second, name))), current);
  assert.deepEqual(Object.keys(JSON.parse(readFileSync(table, "utf8"))).sort(), ["basedOn", "record", "reviewer", "savedAt", "timing"]);
  assert.deepEqual(Object.keys(JSON.parse(readFileSync(status, "utf8"))).sort(), ["errors", "savedAt", "status"]);
});

test("history links at either parent refuse before replacing any current files or review log", () => {
  for (const level of ["history", "artifact"] as const) {
    for (const location of ["inside", "outside"] as const) {
      const f = buildFixture();
      const req = { root: f.root, caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: TABLE, timing, now: NOW };
      saveReviewedTable(req);
      const tables = path.join(f.dir, "answer-tables");
      const target = path.join(location === "inside" ? f.dir : f.outside, "history-target");
      mkdirSync(target);
      writeFileSync(path.join(target, "existing"), "preserved");
      const history = path.join(tables, "history");
      if (level === "artifact") mkdirSync(history);
      symlinkSync(target, level === "history" ? history : path.join(history, "Test002.reviewed-dw"));
      const files = [reviewedFile(f.dir), path.join(tables, "Test002.reviewed-dw.status.json"), path.join(f.dir, "reviews.jsonl")];
      const before = files.map((file) => readFileSync(file));
      assert.throws(() => saveReviewedTable({ ...req, record: edited }), NotFoundError, `${level}/${location}`);
      assert.deepEqual(files.map((file) => readFileSync(file)), before);
      assert.deepEqual(readdirSync(target), ["existing"]);
      assert.equal(readFileSync(path.join(target, "existing"), "utf8"), "preserved");
    }
  }
});


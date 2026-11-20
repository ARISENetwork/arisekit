import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { listBenchmarks } from "../lib/caseset/metrics";
import { archiveProject, DELETED_FOLDER, deletionBlock, INFO_FILE, projectRows, projectTitles, readProjectInfo, saveProjectInfo } from "../lib/project-manage";
import { buildFixture, CASESET } from "./caseset-fixture";

test("a note is trimmed, saved inside the project, and removed when cleared", () => {
  const { root, dir } = buildFixture();
  assert.equal(saveProjectInfo(root, CASESET, { note: "  CLI end-to-end check  " }).note, "CLI end-to-end check");
  assert.deepEqual(JSON.parse(readFileSync(path.join(dir, INFO_FILE), "utf8")), { note: "CLI end-to-end check" });
  assert.equal(projectRows(root, [CASESET])[0].note, "CLI end-to-end check");
  saveProjectInfo(root, CASESET, { note: "   " });
  assert.equal(existsSync(path.join(dir, INFO_FILE)), false);
  assert.throws(() => saveProjectInfo(root, CASESET, { note: "x".repeat(501) }), /under 500 characters/);
  assert.throws(() => saveProjectInfo(root, CASESET, { note: 3 }), /must be text/);
});

test("a display name changes only what the app shows, leaves the note alone, and reads as empty from a malformed file", () => {
  const { root, dir } = buildFixture();
  saveProjectInfo(root, CASESET, { note: "keep" });
  assert.deepEqual(saveProjectInfo(root, CASESET, { title: " Cardiology pilot " }), { title: "Cardiology pilot", note: "keep" });
  assert.deepEqual(projectTitles(root, [CASESET]), { [CASESET]: "Cardiology pilot" });
  assert.equal(projectRows(root, [CASESET])[0].name, CASESET);
  assert.equal(existsSync(dir), true);
  // Naming a project after its own folder clears the display name.
  assert.deepEqual(saveProjectInfo(root, CASESET, { title: CASESET }), { title: "", note: "keep" });
  assert.deepEqual(projectTitles(root, [CASESET]), {});
  assert.throws(() => saveProjectInfo(root, CASESET, { title: "x".repeat(65) }), /under 64 characters/);
  assert.throws(() => saveProjectInfo(root, CASESET, { title: "two\nlines" }), /one line/);
  assert.deepEqual(readProjectInfo(root, CASESET), { title: "", note: "keep" });
  // A malformed project-info.json reads as no display name instead of failing.
  writeFileSync(path.join(dir, INFO_FILE), "{ not json");
  assert.deepEqual(readProjectInfo(root, CASESET), { title: "", note: "" });
  assert.deepEqual(projectTitles(root, [CASESET]), {});
});

test("deleting is refused for the demo, the tutorial and a project with a running pipeline", () => {
  const { root, dir } = buildFixture();
  assert.equal(deletionBlock(root, CASESET), null);
  mkdirSync(path.join(dir, "web-execution"), { recursive: true });
  writeFileSync(path.join(dir, "web-execution", "latest.json"), JSON.stringify({ status: "running" }));
  assert.match(deletionBlock(root, CASESET) ?? "", /running pipeline/);
  mkdirSync(path.join(root, "demo"), { recursive: true });
  assert.match(deletionBlock(root, "demo") ?? "", /bundled demo/);
});

test("a deleted local project moves to the hidden .deleted folder with every file and leaves the list", () => {
  const { root, dir } = buildFixture();
  saveProjectInfo(root, CASESET, { note: "keep me" });
  const moved = archiveProject(root, CASESET, new Date("2026-11-08T03:30:00.000Z"));
  assert.equal(moved, path.join(DELETED_FOLDER, `${CASESET}-2026-11-08T03-30-00-000Z`));
  assert.equal(existsSync(dir), false);
  assert.deepEqual(JSON.parse(readFileSync(path.join(root, moved, INFO_FILE), "utf8")), { note: "keep me" });
  assert.equal(listBenchmarks(root).includes(CASESET), false);
});

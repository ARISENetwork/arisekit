import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { caseIds, projectsRoot } from "../lib/caseset/paths";
import { eachCase } from "./cases";

// Rows with a layout get their own temporary kit folder; the others use a path that is never created.
const ROOTS: Array<{ label: string; root: string; layout?: { dirs: string[]; files?: string[] }; env: (root: string) => Record<string, string>; expected: (root: string) => string }> = [
  { label: "a fresh kit uses the new projects folder", root: "noharm-project-roots-", layout: { dirs: [] },
    env: () => ({}), expected: (root) => path.join(root, "projects") },
  { label: "a legacy casesets folder is still discovered", root: "noharm-project-roots-", layout: { dirs: ["casesets"] },
    env: () => ({}), expected: (root) => path.join(root, "casesets") },
  { label: "the new folder wins when both exist", root: "noharm-project-roots-", layout: { dirs: ["casesets", "projects"] },
    env: () => ({}), expected: (root) => path.join(root, "projects") },
  { label: "an unrelated projects file does not hide an existing legacy directory", root: "noharm-project-file-", layout: { files: ["projects"], dirs: ["casesets"] },
    env: () => ({}), expected: (root) => path.join(root, "casesets") },
  { label: "the legacy variable is still accepted", root: "noharm-test-root",
    env: (root) => ({ NOHARM_CASESETS: path.join(root, "old") }), expected: (root) => path.join(root, "old") },
  { label: "the configured projects variable overrides the legacy one", root: "noharm-test-root",
    env: (root) => ({ NOHARM_PROJECTS: path.join(root, "current"), NOHARM_CASESETS: path.join(root, "old") }), expected: (root) => path.join(root, "current") },
  ...["NOHARM_PROJECTS", "NOHARM_CASESETS"].map((variable) => ({
    label: `a relative ${variable} resolves against the kit for direct frontend launches`, root: "noharm-relative-root",
    env: (): Record<string, string> => ({ [variable]: "custom-projects" }), expected: (root: string): string => path.join(root, "custom-projects"),
  })),
];

test("project roots follow configuration, then the new folder, then legacy discovery", (t) => eachCase(ROOTS, (c) => c.label, (c) => {
  let root = path.join(tmpdir(), c.root);
  if (c.layout) {
    root = mkdtempSync(path.join(tmpdir(), c.root));
    const made = root;
    t.after(() => rmSync(made, { recursive: true, force: true }));
    for (const file of c.layout.files ?? []) writeFileSync(path.join(root, file), "unrelated file");
    for (const dir of c.layout.dirs) mkdirSync(path.join(root, dir));
  }
  assert.equal(projectsRoot(root, c.env(root)), c.expected(root));
}));

test("case listing accepts every case ID the importer accepts", (t) => {
  const dir = mkdtempSync(path.join(tmpdir(), "noharm-case-ids-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  mkdirSync(path.join(dir, "cases"));
  for (const id of ["Case001", "Case001T2R2", "case_01", "Case1-a", "Case1.run1"]) writeFileSync(path.join(dir, "cases", `${id}.json`), "{}");
  assert.deepEqual(caseIds(dir), ["Case001", "Case001T2R2", "case_01"]);
});

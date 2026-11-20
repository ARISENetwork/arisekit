import assert from "node:assert/strict";
import test from "node:test";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { NextRequest } from "next/server";
import { POST } from "../app/api/projects/route";
import type { ProjectFiles } from "../lib/project-files";
import { importProject } from "../lib/project-import";
import { readProjectMode } from "../lib/project-mode-store";
import { buildFixture, CASESET } from "./caseset-fixture";

function projectFiles(folder: string): ProjectFiles {
  return Object.fromEntries(readdirSync(folder, { recursive: true, withFileTypes: true }).filter(file => file.isFile()).map(file => {
    const full = path.join(file.parentPath, file.name);
    return [path.relative(folder, full).split(path.sep).join("/"), readFileSync(full).toString("base64")];
  }));
}

function minimalFiles(mode?: string): ProjectFiles {
  return { "provenance.json": Buffer.from(JSON.stringify({ caseset_name: "alpha", ...(mode ? { execution_mode: mode } : {}) })).toString("base64"),
    "cases/Case001.json": Buffer.from("{}").toString("base64") };
}

test("folder imports preserve cases, rubrics, responses, judgments, and exact source bytes", () => {
  const fixture = buildFixture();
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-import-"));
  try {
    const source = projectFiles(fixture.dir);
    importProject(root, CASESET, source);
    assert.deepEqual(projectFiles(path.join(root, CASESET)), source);
    for (const prefix of ["cases/", "answer-tables/", "results/responses/", "results/judge/"]) assert.ok(Object.keys(source).some(file => file.startsWith(prefix)), prefix);
    assert.throws(() => importProject(root, CASESET, source), /already exists/);
    assert.deepEqual(projectFiles(path.join(root, CASESET)), source);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("invalid folder imports leave no project behind and preserve existing projects", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-bad-import-"));
  const files = minimalFiles();
  try {
    for (const [name, content] of [["../escape", files], ["renamed", files], ["alpha", {}], ["alpha", { ...files, "../outside": "YQ==" }], ["alpha", { ...files, ".env": "YQ==" }], ["alpha", { ...files, broken: "not-base64" }], ["alpha", minimalFiles("unsupported")], ["alpha", { ...files, collision: "YQ==", "collision/nested": "YQ==" }]] as const) {
      assert.throws(() => importProject(root, name, content));
      assert.deepEqual(readdirSync(root), []);
    }
    mkdirSync(path.join(root, "alpha"));
    writeFileSync(path.join(root, "alpha", "keep.txt"), "original");
    assert.throws(() => importProject(root, "alpha", files), /already exists/);
    assert.equal(readFileSync(path.join(root, "alpha", "keep.txt"), "utf8"), "original");
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("folder imports preserve the recorded execution mode without rewriting provenance", () => {
  for (const mode of ["api", "local"]) {
    const root = mkdtempSync(path.join(os.tmpdir(), "noharm-import-mode-"));
    const files = minimalFiles(mode);
    try {
      importProject(root, "alpha", files);
      assert.equal(readProjectMode(root, "alpha"), mode);
      assert.deepEqual(projectFiles(path.join(root, "alpha")), files);
    } finally { rmSync(root, { recursive: true, force: true }); }
  }
});

test("the import endpoint selects the imported project and rejects replacement and foreign origins", async () => {
  const fixture = buildFixture();
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-import-api-"));
  const previous = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = root;
  const request = (origin = "http://localhost") => new NextRequest("http://localhost/api/projects", { method: "POST", headers: { origin, "Content-Type": "application/json" }, body: JSON.stringify({ name: CASESET, files: projectFiles(fixture.dir) }) });
  try {
    assert.equal((await POST(request("https://other.example"))).status, 403);
    assert.deepEqual(readdirSync(root), []);
    const response = await POST(request());
    assert.equal(response.status, 201);
    assert.deepEqual(await response.json(), { project: CASESET, href: "/noharm/dashboard" });
    assert.equal(response.cookies.get("noharm-benchmark")?.value, CASESET);
    assert.deepEqual(projectFiles(path.join(root, CASESET)), projectFiles(fixture.dir));
    assert.equal((await POST(request())).status, 409);
  } finally {
    if (previous === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = previous;
    rmSync(root, { recursive: true, force: true });
  }
});

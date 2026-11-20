import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { NextRequest } from "next/server";
import { POST as create } from "../app/api/projects/route";
import { POST as resume } from "../app/api/benchmark/route";
import { loadBenchmark } from "../lib/caseset/metrics";
import { rubricHandoff } from "../lib/dataset-import";
import { createProject } from "../lib/project-create";
import { projectMode } from "../lib/project-mode";
import { readProjectMode, saveProjectMode } from "../lib/project-mode-store";
import { TEXT_V2_PIPELINE_V2_COMMIT } from "../lib/text-v2-runtime";

test("project modes default to API and reject unknown or malformed values", () => {
  assert.equal(projectMode(undefined), "api");
  for (const mode of ["api", "local"]) assert.equal(projectMode(mode), mode);
  for (const mode of [null, "", "subscription", "openrouter", {}, false]) assert.throws(() => projectMode(mode), /Choose API Mode or Local Mode/);
});

test("saving a mode preserves existing provenance and outputs, and unchanged modes do not rewrite metadata", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-mode-"));
  createProject(root, "project", "Existing idea");
  const file = path.join(root, "project", "provenance.json");
  const initial = { caseset_name: "project", trials: 3, cases: ["Case001"], models: ["codex:existing"], custom: { preserve: true }, updated_at: "2026-01-01", frozen: { backend: "openai" } };
  writeFileSync(file, JSON.stringify(initial));
  const output = path.join(root, "project", "items.jsonl");
  writeFileSync(output, '{"existing":"output"}\n');
  const outputBefore = readFileSync(output, "utf8");
  assert.equal(readProjectMode(root, "project"), "api");
  assert.equal(readFileSync(file, "utf8"), JSON.stringify(initial));
  assert.equal(saveProjectMode(root, "project", "local"), true);
  const saved = JSON.parse(readFileSync(file, "utf8"));
  const { execution_mode, updated_at, ...preserved } = saved;
  const { updated_at: priorDate, ...prior } = initial;
  assert.equal(execution_mode, "local");
  assert.notEqual(updated_at, priorDate);
  assert.deepEqual(preserved, prior);
  assert.equal(readProjectMode(root, "project"), "local");
  assert.equal(readFileSync(output, "utf8"), outputBefore);
  const before = readFileSync(file, "utf8");
  assert.equal(saveProjectMode(root, "project", "local"), false);
  assert.equal(readFileSync(file, "utf8"), before);
  assert.equal(saveProjectMode(root, "project", "api"), true);
  assert.equal(readProjectMode(root, "project"), "api");
  assert.deepEqual(readdirSync(path.join(root, "project")).sort(), ["cases", "items.jsonl", "provenance.json"]);
  assert.throws(() => saveProjectMode(root, "../outside", "api"));
});

test("invalid provenance and links outside a project are rejected without rewriting data", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-mode-invalid-"));
  createProject(root, "project", "");
  const file = path.join(root, "project", "provenance.json");
  for (const raw of ["null", "[]", "{", '{"execution_mode":"unsupported"}']) {
    writeFileSync(file, raw);
    assert.throws(() => readProjectMode(root, "project"));
    if (!raw.includes("unsupported")) assert.throws(() => saveProjectMode(root, "project", "local"));
    assert.equal(readFileSync(file, "utf8"), raw);
  }
  const before = readFileSync(file, "utf8");
  assert.throws(() => saveProjectMode(root, "project", "invalid"), /Choose API Mode or Local Mode/);
  assert.equal(readFileSync(file, "utf8"), before);
  mkdirSync(path.join(root, "linked"));
  const linkedFile = path.join(root, "linked", "provenance.json");
  symlinkSync(file, linkedFile);
  assert.throws(() => saveProjectMode(root, "linked", "local"), /outside/);
  assert.throws(() => readProjectMode(root, "linked"), /outside/);
  assert.equal(readFileSync(file, "utf8"), before);
});

test("creation and resume APIs need no agent, select the project, persist both modes, and reject foreign, duplicate, bad-name, and invalid-mode requests before selecting or writing", async () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-mode-api-"));
  const previous = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = root;
  const createRequest = (name: string, mode?: unknown): NextRequest => new NextRequest("http://localhost/api/projects", {
    method: "POST", headers: { origin: "http://localhost", "Content-Type": "application/json" }, body: JSON.stringify({ name, idea: "", ...(mode === undefined ? {} : { execution_mode: mode }) }),
  });
  const resumeRequest = (mode: string, origin = "http://localhost"): NextRequest => new NextRequest("http://localhost/api/benchmark", {
    method: "POST", headers: { origin, Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ benchmark: "local-project", execution_mode: mode, returnTo: "/noharm/dashboard" }).toString(),
  });
  const foreignRequest = new NextRequest("http://localhost/api/projects", { method: "POST", headers: { origin: "https://other.example", "Content-Type": "application/json" }, body: JSON.stringify({ name: "created", idea: "" }) });
  try {
    assert.equal((await create(foreignRequest)).status, 403);
    assert.deepEqual(readdirSync(root), []);
    for (const [name, mode] of [["api-project", undefined], ["local-project", "local"]] as const) {
      const response = await create(createRequest(name, mode));
      assert.equal(response.status, 201);
      assert.deepEqual(await response.json(), { project: name, href: mode === "local" ? "/noharm/dataset" : "/noharm/api-setup" });
      assert.equal(response.cookies.get("noharm-benchmark")!.value, name);
      assert.equal(readProjectMode(root, name), mode ?? "api");
    }
    assert.equal((await create(createRequest("api-project"))).status, 409);
    assert.equal((await create(createRequest("../bad"))).status, 400);
    assert.equal((await create(createRequest("invalid-project", "bad"))).status, 400);
    assert.deepEqual(readdirSync(root), ["api-project", "local-project"]);
    const savedFile = path.join(root, "local-project", "provenance.json");
    for (const mode of ["invalid", "", "subscription"]) {
      const before = readFileSync(savedFile, "utf8");
      const response = await resume(resumeRequest(mode));
      assert.equal(response.status, 400);
      assert.equal(response.headers.get("set-cookie"), null);
      assert.equal(readFileSync(savedFile, "utf8"), before);
    }
    for (const mode of ["api", "local"]) {
      const response = await resume(resumeRequest(mode));
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { project: "local-project", href: mode === "api" ? "/noharm/api-setup" : "/noharm/dashboard" });
      assert.equal(response.cookies.get("noharm-benchmark")?.value, "local-project");
      assert.equal(readProjectMode(root, "local-project"), mode);
      assert.equal(readProjectMode(root, "api-project"), "api");
    }
    assert.equal((await resume(resumeRequest("api", "https://other.example"))).status, 403);
    assert.equal(readProjectMode(root, "local-project"), "local");
  } finally {
    if (previous === undefined) delete process.env.NOHARM_PROJECTS;
    else process.env.NOHARM_PROJECTS = previous;
  }
});

test("local creation produces an empty pipeline-compatible project without replacing another project", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-create-"));
  createProject(root, "new-project", "My benchmark idea");
  assert.deepEqual(readdirSync(root), ["new-project"]);
  assert.deepEqual(readdirSync(path.join(root, "new-project", "cases")), []);
  assert.equal(readFileSync(path.join(root, "new-project", "items.jsonl"), "utf8"), "");
  const provenance = JSON.parse(readFileSync(path.join(root, "new-project", "provenance.json"), "utf8"));
  assert.equal(provenance.caseset_name, "new-project");
  assert.equal(provenance.trials, 1);
  assert.equal(provenance.judge_scoring_source_commit, TEXT_V2_PIPELINE_V2_COMMIT);
  assert.equal(provenance.description, "My benchmark idea");
  assert.deepEqual(loadBenchmark(root, "new-project").cases, []);
  assert.throws(() => createProject(root, "new-project", "Changed"), /EEXIST/);
  assert.equal(JSON.parse(readFileSync(path.join(root, "new-project", "provenance.json"), "utf8")).description, "My benchmark idea");
  assert.throws(() => createProject(root, "../escape", ""), /Project name/);
  assert.deepEqual(readdirSync(root), ["new-project"]);
});

test("manual dataset generation names the selected project in the external-agent handoff", () => {
  const prompt = rubricHandoff([{ task: "My task", solutions: ["My solution"], errors: "" }], null, false, "new-project");
  assert.match(prompt, /for project "new-project"/);
  assert.match(prompt, /Source: user-entered dataset/);
});

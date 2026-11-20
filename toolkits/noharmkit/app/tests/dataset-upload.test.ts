import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, symlinkSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { saveDatasetUpload } from "../lib/dataset-upload";
import { uploadedDatasetHandoff } from "../lib/dataset-import";
import { GET, POST } from "../app/api/dataset-upload/route";
import { NextRequest } from "next/server";

test("upload storage", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-upload-"));
  mkdirSync(path.join(root, "chosen")); mkdirSync(path.join(root, "other"));
  const bytes = new TextEncoder().encode('\uFEFFTask,Solution,Errors\r\n"Case, one","Answer A; Answer B",Error\r\n');
  const first = saveDatasetUpload(root, "chosen", "cases.csv", bytes);
  const second = saveDatasetUpload(root, "chosen", "cases.csv", bytes);
  assert.notEqual(first.path, second.path);
  assert.deepEqual(readFileSync(first.path), Buffer.from(bytes));
  assert.deepEqual(readFileSync(second.path), Buffer.from(bytes));
  assert.deepEqual(readdirSync(path.join(root, "other")), []);
  assert.equal(readdirSync(path.join(root, "chosen", "imports")).length, 2);
  assert.equal(first.bytes, bytes.length);

  // Refuses unknown projects, unsafe filenames, and an imports directory outside the project.
  const refusing = mkdtempSync(path.join(os.tmpdir(), "noharm-upload-"));
  mkdirSync(path.join(refusing, "chosen")); mkdirSync(path.join(refusing, "other"));
  assert.throws(() => saveDatasetUpload(refusing, "missing", "a.csv", new Uint8Array()), /no project/);
  assert.throws(() => saveDatasetUpload(refusing, "chosen", "../a.csv", new Uint8Array()), /plain filename/);
  symlinkSync(path.join(refusing, "other"), path.join(refusing, "chosen", "imports"));
  assert.throws(() => saveDatasetUpload(refusing, "chosen", "a.json", new Uint8Array()), /outside/);
  assert.deepEqual(readdirSync(path.join(refusing, "other")), []);
});
test("the agent handoff names the project and original file and delegates parsing", () => {
  const prompt = uploadedDatasetHandoff("chosen", "/repo/projects/chosen/imports/id/cases.csv");
  assert.match(prompt, /project "chosen"/);
  assert.match(prompt, /\/repo\/projects\/chosen\/imports\/id\/cases.csv/);
});

test("upload API requires an explicit existing project and saves unparsed source bytes", async () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-upload-api-"));
  mkdirSync(path.join(root, "chosen"));
  const previous = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = root;
  try {
    assert.deepEqual((await (await GET()).json()).projects, ["chosen"]);
    const form = new FormData(); form.set("project", "chosen"); form.set("file", new File(["Original source, not browser-parsed"], "source.csv"));
    const result = await POST(new NextRequest("http://localhost/api/dataset-upload", { method: "POST", body: form }));
    assert.equal(result.status, 201);
    const saved = await result.json();
    assert.equal(saved.project, "chosen");
    assert.equal(readFileSync(saved.path, "utf8"), "Original source, not browser-parsed");
    const missing = new FormData(); missing.set("file", new File(["{}"], "a.json"));
    assert.equal((await POST(new NextRequest("http://localhost/api/dataset-upload", { method: "POST", body: missing }))).status, 400);
    assert.equal((await POST(new NextRequest("http://localhost/api/dataset-upload", { method: "POST", body: form, headers: { origin: "http://other.example" } }))).status, 403);
  } finally { if (previous === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = previous; }
});

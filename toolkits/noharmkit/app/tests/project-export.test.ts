import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gunzipSync } from "node:zlib";
import { exportableProjectPath, projectArchiveStream, projectExportInventory } from "../lib/project-export";

function fixture(): { root: string; folder: string } {
  const root = mkdtempSync(path.join(os.tmpdir(), "project-export-"));
  const folder = path.join(root, "alpha");
  mkdirSync(folder);
  return { root, folder };
}
function entries(bytes: Buffer): Record<string, Buffer> {
  const files: Record<string, Buffer> = {};
  let longName: string | undefined;
  for (let at = 0; at < bytes.length && bytes[at];) {
    const name = bytes.subarray(at, at + 100).toString().split("\0")[0];
    const size = parseInt(bytes.subarray(at + 124, at + 136).toString().split("\0")[0], 8);
    const content = bytes.subarray(at + 512, at + 512 + size);
    if (bytes[at + 156] === 76) longName = content.toString().replace(/\0$/, "");
    else { files[longName ?? name] = content; longName = undefined; }
    at += 512 + Math.ceil(size / 512) * 512;
  }
  return files;
}

test("project export preserves artifacts and byte hashes while omitting restricted paths", async () => {
  const { root, folder } = fixture();
  mkdirSync(path.join(folder, "cases"));
  const kept = { "provenance.json": Buffer.from('{"trials":2}\n'), "imports/source.csv": Buffer.from([0, 255, 10]), "answer-tables/Case001.run1.json": Buffer.from("rubric\n"), "results/responses/model.jsonl": Buffer.from("response\n"), "web-execution/latest.json": Buffer.from("receipt\n"), "api-pipeline.json": Buffer.from('{"parallel":2}'), [`results/${"long-name-".repeat(13)}.json`]: Buffer.from("long path") };
  for (const [name, data] of Object.entries(kept)) { mkdirSync(path.dirname(path.join(folder, name)), { recursive: true }); writeFileSync(path.join(folder, name), data); }
  for (const name of [".env", "credentials.json", "results/api-key.json", "results/secret.txt", "results/old.tmp", "results/debug.log", "holdout/private.json", "inputs/held-HOLDOUT-data.json"]) { mkdirSync(path.dirname(path.join(folder, name)), { recursive: true }); writeFileSync(path.join(folder, name), "excluded"); }
  symlinkSync(path.join(folder, "provenance.json"), path.join(folder, "linked.json"));
  const { manifest } = await projectExportInventory(root, "alpha");
  assert.equal(manifest.fileCount, Object.keys(kept).length);
  assert.equal(manifest.excludedCount, 9);
  const downloaded = Buffer.from(await new Response(projectArchiveStream(folder, manifest)).arrayBuffer());
  const archive = entries(gunzipSync(downloaded));
  assert.deepEqual(JSON.parse(archive["ARISEKIT-EXPORT.json"].toString()), manifest);
  assert.deepEqual(Object.keys(archive).filter(name => !name.endsWith("/")).sort(), ["ARISEKIT-EXPORT.json", ...Object.keys(kept).map(name => `project/${name}`)].sort());
  assert.ok(Object.hasOwn(archive, "project/cases/"));
  const downloadedFile = path.join(root, "download.tar.gz");
  writeFileSync(downloadedFile, downloaded);
  for (const [name, data] of Object.entries(kept)) {
    assert.deepEqual(execFileSync("tar", ["-xOzf", downloadedFile, `project/${name}`]), data);
    assert.deepEqual(archive[`project/${name}`], data);
    const row = manifest.files.find(file => file.path === name)!;
    assert.equal(row.bytes, data.length);
    assert.equal(row.sha256, createHash("sha256").update(data).digest("hex"));
  }
});

test("project export refuses traversal and missing projects and skips escaping links", async () => {
  const { root, folder } = fixture();
  for (const relative of ["../outside", "/absolute", "cases\\outside", "cases/holdout-copy.json", "cases/.hidden/x", "keys/private-key.pem"]) assert.equal(exportableProjectPath(relative), false, relative);
  await assert.rejects(projectExportInventory(root, "../outside"), /no project/);
  await assert.rejects(projectExportInventory(root, "other-account"), /no project/);
  symlinkSync(os.tmpdir(), path.join(folder, "outside"));
  assert.equal((await projectExportInventory(root, "alpha")).manifest.fileCount, 0);
});

test("a changed project file fails the streamed archive instead of publishing a mismatched inventory", async () => {
  const { root, folder } = fixture();
  writeFileSync(path.join(folder, "items.jsonl"), "before");
  const { manifest } = await projectExportInventory(root, "alpha");
  writeFileSync(path.join(folder, "items.jsonl"), "after!");
  await assert.rejects(new Response(projectArchiveStream(folder, manifest)).arrayBuffer(), /changed during export/);
});

test("download route only exports projects in the current workspace and disables caching", async () => {
  const { root, folder } = fixture();
  writeFileSync(path.join(folder, "items.jsonl"), "case\n");
  const previous = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = root;
  try {
    const { NextRequest } = await import("next/server");
    const { GET } = await import("../app/api/projects/export/route");
    const request = (project: string): InstanceType<typeof NextRequest> => new NextRequest(`http://localhost/api/projects/export?project=${encodeURIComponent(project)}`);
    for (const name of ["../outside", "other-account"]) assert.equal((await GET(request(name))).status, name.startsWith("..") ? 400 : 404);
    const response = await GET(request("alpha"));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("Cache-Control"), "private, no-store");
    assert.equal(response.headers.get("Content-Disposition"), 'attachment; filename="alpha-project.tar.gz"');
    const files = entries(gunzipSync(Buffer.from(await response.arrayBuffer())));
    assert.equal(files["project/items.jsonl"].toString(), "case\n");
  } finally {
    if (previous === undefined) delete process.env.NOHARM_PROJECTS;
    else process.env.NOHARM_PROJECTS = previous;
  }
});

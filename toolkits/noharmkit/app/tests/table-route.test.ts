import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { NextRequest } from "next/server";

import { PUT } from "../app/api/runs/table/route";
import { newTiming } from "../lib/answer-table";
import { loadEditorPayload } from "../lib/caseset/editor";
import { buildFixture, CASESET, TABLE } from "./caseset-fixture";

function request(body: unknown, origin?: string, host?: string): NextRequest {
  return new NextRequest("http://localhost:43187/api/runs/table", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(origin ? { Origin: origin } : {}), ...(host ? { Host: host } : {}) },
    body: JSON.stringify(body),
  });
}

test("table saves reject foreign origins and require loaded source and replacement identities", async () => {
  const f = buildFixture();
  const prior = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = f.root;
  try {
    const payload = loadEditorPayload(f.root, CASESET, "Test002", "run1", "dw");
    const body = { caseset: CASESET, caseId: "Test002", version: "run1", reviewer: "dw", record: TABLE, timing: newTiming(new Date()), sourceSha256: payload.sourceSha256, replacesSha256: payload.replacesSha256 };
    assert.equal((await PUT(request(body, "https://evil.example"))).status, 403);
    assert.equal((await PUT(request({ ...body, sourceSha256: undefined }))).status, 400);
    assert.equal((await PUT(request({ ...body, replacesSha256: undefined }))).status, 400);
    assert.equal((await PUT(request({ ...body, sourceSha256: "bad" }))).status, 400);
    assert.equal((await PUT(request({ ...body, replacesSha256: "bad" }))).status, 400);
    const first = await PUT(request(body, "http://localhost:43187"));
    assert.equal(first.status, 200);
    const saved = await first.json();
    const files = ["answer-tables/Test002.reviewed-dw.json", "answer-tables/Test002.reviewed-dw.status.json", "reviews.jsonl"];
    const before = files.map((file) => readFileSync(path.join(f.dir, file), "utf8"));
    assert.equal((await PUT(request(body))).status, 409, "An absent replacement copied before creation cannot overwrite the new copy.");
    assert.deepEqual(files.map((file) => readFileSync(path.join(f.dir, file), "utf8")), before);
    assert.equal((await PUT(request({ ...body, replacesSha256: saved.contentSha256 }))).status, 200, "Repeated saves from the opened generated version preserve its source identity.");
    const own = loadEditorPayload(f.root, CASESET, "Test002", "reviewed-dw", "dw");
    assert.equal((await PUT(request({ ...body, version: "reviewed-dw", sourceSha256: own.sourceSha256, replacesSha256: own.replacesSha256 }, "http://kit.example:43187", "kit.example:43187"))).status, 200, "The request host supports network access and re-saving the own copy.");
    assert.equal((await PUT(request({ ...body, sourceSha256: "0".repeat(64), replacesSha256: saved.contentSha256 }))).status, 409);
  } finally {
    if (prior === undefined) delete process.env.NOHARM_PROJECTS;
    else process.env.NOHARM_PROJECTS = prior;
  }
});

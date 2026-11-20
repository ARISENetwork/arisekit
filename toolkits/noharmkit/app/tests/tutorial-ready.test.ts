import assert from "node:assert/strict";
import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { NextRequest } from "next/server";
import { buildFixture, CASESET } from "./caseset-fixture";

const { root } = buildFixture();
process.env.NOHARM_PROJECTS = root;
const benchmark = "tutorial-11111111-1111-4111-8111-111111111111";
renameSync(path.join(root, CASESET), path.join(root, benchmark));
const tables = path.join(root, benchmark, "answer-tables");

test("tutorial readiness requires a saved passing rubric and an existing tutorial project", async () => {
  const { GET } = await import("../app/api/benchmark/route");
  const request = (): NextRequest => new NextRequest(`http://localhost:9000/api/benchmark?benchmark=${benchmark}`);
  for (const version of ["run1", "run2", "run3"]) writeFileSync(path.join(tables, `Test002.${version}.status.json`), JSON.stringify({ status: "failed", errors: ["Generation failed"] }));
  assert.deepEqual(await (await GET(request())).json(), { ready: false });
  writeFileSync(path.join(tables, "Test002.run1.status.json"), JSON.stringify({ status: "pass", errors: [] }));
  assert.deepEqual(await (await GET(request())).json(), { ready: true });
  writeFileSync(path.join(tables, "Test002.run1.json"), "null");
  assert.deepEqual(await (await GET(request())).json(), { ready: false });
  const empty = "tutorial-22222222-2222-4222-8222-222222222222";
  mkdirSync(path.join(root, empty));
  for (const name of [empty, "tutorial-33333333-3333-4333-8333-333333333333"]) {
    const response = await GET(new NextRequest(`http://localhost:9000/api/benchmark?benchmark=${name}`));
    assert.deepEqual(await response.json(), { ready: false });
  }
  assert.equal((await GET(new NextRequest("http://localhost:9000/api/benchmark?benchmark=demo"))).status, 400);
});

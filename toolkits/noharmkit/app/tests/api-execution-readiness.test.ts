import assert from "node:assert/strict";
import test from "node:test";
import { NextRequest } from "next/server";
import { executionReadiness } from "../lib/api-execution-readiness";
import { GET as getReadiness } from "../app/api/pipeline/readiness/route";
import { PATCH as stopApi } from "../app/api/pipeline/run/route";

test("readiness distinguishes missing runtime, missing credentials, and deterministic scoring", () => {
  const missingPython = executionReadiness({ hasApiKey: true, pythonError: "The project Python runtime is unavailable." });
  assert.equal(missingPython.modelCalls.available, false);
  assert.equal(missingPython.scoring.available, false);
  assert.match(missingPython.scoring.reason, /Python runtime/);
  const missingKey = executionReadiness({ hasApiKey: false });
  assert.equal(missingKey.modelCalls.available, false);
  assert.equal(missingKey.scoring.available, true);
  assert.match(missingKey.modelCalls.reason, /OPENROUTER_API_KEY/);
  assert.equal(executionReadiness({ hasApiKey: true }).modelCalls.available, true);
});

test("readiness describes the local model and scoring runtime", async () => {
  const response = getReadiness();
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(Object.keys(await response.json()).sort(), ["modelCalls", "scoring"]);
});

test("stop control rejects a foreign origin before inspecting or changing any run", async () => {
  const response = await stopApi(new NextRequest("http://localhost/api/pipeline/run", { method: "PATCH", headers: { origin: "https://other.example", "Content-Type": "application/json" }, body: JSON.stringify({ project: "example", jobId: "job" }) }));
  assert.equal(response.status, 403);
});

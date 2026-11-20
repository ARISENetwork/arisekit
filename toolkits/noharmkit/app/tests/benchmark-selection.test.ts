import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { NextRequest } from "next/server";

import { POST } from "../app/api/benchmark/route";
import { BENCHMARK_COOKIE, resolveBenchmarkSelection, safeBenchmarkReturnPath } from "../lib/caseset/selection";
import { STEP_KEYS } from "../lib/caseset/steps";
import { buildFixture, CASESET } from "./caseset-fixture";
import { eachCase } from "./cases";

const SAVED_FIRST = { names: ["saved", "configured", "newest"], dates: { saved: null, configured: "2026-09-01", newest: "2026-09-29" } };
const STALE = { names: ["alpha", "beta"], dates: { alpha: "2026-09-01", beta: "2026-09-29" } };
const SELECTION_CASES: { label: string; names: string[]; dates: Record<string, string | null>; saved: string | undefined; configured: string | undefined; expected: string | null }[] = [
  { label: "saved project overrides configured and newest", ...SAVED_FIRST, saved: "saved", configured: "configured", expected: "saved" },
  { label: "configured project without a saved choice", ...SAVED_FIRST, saved: undefined, configured: "configured", expected: "configured" },
  { label: "stale saved choice falls back to configured", ...STALE, saved: "removed", configured: "alpha", expected: "alpha" },
  { label: "stale saved and configured fall back to newest", ...STALE, saved: "removed", configured: "removed", expected: "beta" },
  { label: "no choices pick the newest", ...STALE, saved: undefined, configured: undefined, expected: "beta" },
  { label: "no dates pick the first sorted name", names: ["beta", "alpha"], dates: {}, saved: undefined, configured: undefined, expected: "alpha" },
  { label: "no projects select nothing", names: [], dates: {}, saved: "saved", configured: "configured", expected: null },
];

test("project selection precedence", () => eachCase(SELECTION_CASES, (c) => c.label, (c) => {
  assert.equal(resolveBenchmarkSelection(c.names, c.dates, c.saved, c.configured), c.expected);
}));

const RETURN_CASES: { input: string | null | undefined; expected: string }[] = [
  ...["/welcome", "/dashboard", "/dataset", "/inputs", "/framework", "/guide", "/api-setup", ...STEP_KEYS.map((step) => `/${step}`)].map(local => ({ input: `/noharm${local}`, expected: `/noharm${local}` })),
  { input: "/noharm/review", expected: "/noharm/rubrics" },
  ...[undefined, null, "/", "/dataset", "/noharm/cases?case=Other001", "/noharm/rubrics/Other001", "/noharm//evil.example", "//evil.example", "https://evil.example", "/\\evil.example", "/api/benchmark",
    "/noharm/dashboard?review=dashboard-01&context=clear&counts=units&onboarding=focused&original=1&case=Other001&mode=authoring",
    "/noharm/dashboard?review=dashboard-01&context=invalid&counts=units&redirect=https://evil.example",
    "/noharm/dashboard?review=unknown&counts=units",
    "https://evil.example/noharm/dashboard?review=dashboard-01",
  ].map(input => ({ input, expected: "/noharm/welcome" })),
];

test("safe return paths", () => eachCase(RETURN_CASES, (c) => `${String(c.input)} -> ${c.expected}`, (c) => {
  assert.equal(safeBenchmarkReturnPath(c.input), c.expected);
}));

function request(benchmark: string | undefined, returnTo = "/noharm/leaderboard", origin?: string, site = "http://localhost:43188"): NextRequest {
  const form = new URLSearchParams({ returnTo });
  if (benchmark !== undefined) form.set("benchmark", benchmark);
  return new NextRequest(`${site}/api/benchmark`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Cookie: `${BENCHMARK_COOKIE}=prior`, ...(origin ? { Origin: origin } : {}) },
    body: form.toString(),
  });
}

test("project API selects a known project with a scoped persistent cookie", async (t) => {
  const fixture = buildFixture();
  mkdirSync(path.join(fixture.root, "new-project"));
  const prior = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = fixture.root;
  t.after(() => {
    if (prior === undefined) delete process.env.NOHARM_PROJECTS;
    else process.env.NOHARM_PROJECTS = prior;
  });

  const response = await POST(request("new-project", "/noharm/leaderboard", "http://localhost:43188"));
  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "http://localhost:43188/noharm/leaderboard");
  const cookie = response.cookies.get(BENCHMARK_COOKIE);
  assert.equal(cookie?.name, BENCHMARK_COOKIE);
  assert.equal(cookie?.value, "new-project");
  assert.equal(cookie?.path, "/");
  assert.equal(cookie?.httpOnly, true);
  assert.equal(cookie?.sameSite, "lax");
  assert.equal(cookie?.maxAge, 31536000);

  const tailscale = "http://100.82.229.78:43188";
  const remote = await POST(request(CASESET, "/noharm/review", tailscale, tailscale));
  assert.equal(remote.status, 303);
  assert.equal(remote.headers.get("location"), `${tailscale}/noharm/rubrics`);

  for (const site of ["http://localhost:43188", tailscale]) {
    const boundRequest = request(CASESET, "/noharm/leaderboard", site, "http://0.0.0.0:43188");
    boundRequest.headers.set("host", new URL(site).host);
    const boundResponse = await POST(boundRequest);
    assert.equal(boundResponse.status, 303);
    assert.equal(boundResponse.headers.get("location"), `${site}/noharm/leaderboard`);
    boundRequest.headers.set("origin", "https://evil.example");
    assert.equal((await POST(boundRequest)).status, 403);
  }

  for (const returnTo of ["//evil.example", "https://evil.example", "/noharm/cases?case=Other001"]) {
    const sanitized = await POST(request(CASESET, returnTo));
    assert.equal(sanitized.status, 303);
    assert.equal(sanitized.headers.get("location"), "http://localhost:43188/noharm/welcome");
  }

  for (const benchmark of [undefined, "unknown", "../outside", "linked", "legacy", `${CASESET}/../legacy`]) {
    const rejected = await POST(request(benchmark));
    assert.equal(rejected.status, 400);
    assert.equal(rejected.headers.get("set-cookie"), null);
  }

  const crossOrigin = await POST(request(CASESET, "/noharm/leaderboard", "https://evil.example"));
  assert.equal(crossOrigin.status, 403);
  assert.equal(crossOrigin.headers.get("set-cookie"), null);

  const invalidForm = await POST(new NextRequest("http://localhost:43188/api/benchmark", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }));
  assert.equal(invalidForm.status, 400);
  assert.equal(invalidForm.headers.get("set-cookie"), null);
});

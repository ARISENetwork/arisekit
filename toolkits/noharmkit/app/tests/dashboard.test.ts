import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import Dashboard from "../components/mc/Dashboard";
import { loadBenchmark } from "../lib/caseset/metrics";
import type { Benchmark } from "../lib/caseset/metrics";
import { stepHref } from "../lib/caseset/routes";
import { STEP_KEYS } from "../lib/caseset/steps";
import { buildFixture, CASESET } from "./caseset-fixture";
import { eachCase } from "./cases";

const blank: Benchmark = {
  name: "blank-project", cases: [], updatedAt: null, models: [], attention: [], needAttention: 0,
  awaiting: { rubrics: 0, autograding: 0 }, meanF1: { value: null, n: 0, draft: false, provisional: false }, byModel: [],
  steps: Object.fromEntries(STEP_KEYS.map((key) => [key, {
    key, done: 0, total: 0, reviewed: key === "cases" || key === "responses" ? null : 0,
    reviewTotal: key === "cases" || key === "responses" ? null : 0, failed: 0, dot: "none",
  }])) as Benchmark["steps"],
};
const render = (bench: Benchmark, exampleProject?: string): string => renderToStaticMarkup(createElement(Dashboard, {
  bench, projectsRoot: "/tmp/projects", exampleProject,
}));
const fixture = buildFixture();
const populated = loadBenchmark(fixture.root, CASESET);
const synthetic: Benchmark = { ...populated, name: "demo", cases: populated.cases.map((c) => ({
  ...c, page: { ...c.page, provenance: { ...c.page.provenance, synthetic: true } },
})) };

for (const bench of [blank, populated]) {
  test(`${bench.name}: pipeline carries step links and meters`, () => {
    const before = JSON.stringify(bench);
    const html = render(bench);
    assert.ok(html.includes(">Pipeline</h2>"));
    for (const step of STEP_KEYS) assert.ok(html.includes(`href="${stepHref(step)}"`));
    assert.ok(html.includes("models with scores"));
    assert.doesNotMatch(html, /Mean F1|Attention items|Nothing needs attention|<h2[^>]*>Models</);
    assert.equal(JSON.stringify(bench), before);
  });
}

test("no project points all pipeline cards at project creation", () => {
  const html = render({ ...blank, name: "" });
  assert.equal((html.match(/href="\/noharm\/welcome#new-project"/g) ?? []).length, 6);
  assert.doesNotMatch(html, /Review and issues/);
});

const PANEL_CASES: { label: string; bench: Benchmark; once: RegExp[]; match: RegExp[]; absent: RegExp[] }[] = [
  {
    label: "pending rubric review appears once as actionable work without an all-clear message",
    bench: { ...populated, attention: [], awaiting: { rubrics: 1, autograding: 2 } },
    once: [/>Review and issues</g, /Selected or previously used rubrics not yet reviewed/g],
    match: [/href="\/noharm\/rubrics"/],
    absent: [/Nothing needs attention|LLM grades not yet reviewed|Awaiting rubric review/, /Welcome to NOHARMKit/],
  },
  {
    label: "an issue keeps its exact record target and count without pending review",
    bench: { ...populated, awaiting: { rubrics: 0, autograding: 0 }, attention: [{
      key: "staleAutograding", label: "Out-of-date mappings", detail: "Inputs changed", count: 2,
      step: "autograding", cases: ["Test002"], target: { case: "Test002", model: "model-a", trial: 2 },
    }] },
    once: [],
    match: [/Review and issues/, /href="\/noharm\/autograding\?case=Test002&amp;model=model-a&amp;trial=2"/, /Out-of-date mappings/, /Inputs changed/, />2</],
    absent: [/Welcome to NOHARMKit/],
  },
];

test("review and issues panel", () => eachCase(PANEL_CASES, (c) => c.label, (c) => {
  const html = render(c.bench);
  for (const pattern of c.once) assert.equal((html.match(pattern) ?? []).length, 1, String(pattern));
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
}));

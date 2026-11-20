import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createRequire } from "node:module";

import { loadBenchmark, type Benchmark } from "../lib/caseset/metrics";
import { welcomeMode, resumableProjects } from "../lib/onboarding";
import { buildFixture, CASESET, MODEL_A } from "./caseset-fixture";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const Welcome = require("../components/mc/Welcome").default as typeof import("../components/mc/Welcome").default;
const Leaderboard = require("../components/mc/steps/LeaderboardStep").default as typeof import("../components/mc/steps/LeaderboardStep").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const pane = (html: string, name: string): string => html.match(new RegExp(`<section[^>]*aria-label="${name}"[^>]*>`))?.[0] ?? "";

test("welcome offers a choice even with no projects or only the demo", () => {
  assert.equal(welcomeMode([], undefined, undefined), "entry");
  assert.equal(welcomeMode(["demo"], "demo", undefined), "entry");
  assert.equal(welcomeMode(["demo", "vascular"], "demo", undefined), "entry");
  for (const mode of ["new", "resume"] as const) assert.equal(welcomeMode(["vascular"], undefined, mode), mode);
  assert.equal(welcomeMode(["vascular"], undefined, "invalid"), "entry");
  assert.equal(welcomeMode(["vascular"], undefined, "tutorial"), "entry");
});

test("returning welcome leads with resume; learning resources follow", () => {
  const { root } = buildFixture();
  const bench = loadBenchmark(root, CASESET);
  const html = renderToStaticMarkup(createElement(Welcome, { bench, projects: ["demo", CASESET], exampleProject: "demo" }));
  assert.ok(pane(html, "Get started"));
  assert.ok(pane(html, "Learn NOHARMKit"));
  assert.match(html, /Welcome back to NOHARM/);
  assert.match(html, /<button[^>]*aria-haspopup="dialog"[^>]*>Resume project<\/button>/);
  assert.match(html, /<button[^>]*aria-haspopup="dialog"[^>]*>Create project<\/button>/);
  assert.match(html, /href="\/noharm\/projects"[^>]*>Manage projects</);
  assert.match(html, /Replay walkthrough/);
  assert.match(html, /href="\/noharm\/guide"/);
  assert.match(html, /href="\/noharm\/framework"/);
  assert.match(html, /Review scoring framework/);
  assert.doesNotMatch(html, /data-recommended="true"|Start walkthrough|Work on a Project/);
});

test("a new visitor gets one primary action: the walkthrough, then project creation", () => {
  const { root } = buildFixture();
  const bench = loadBenchmark(root, CASESET);
  const html = renderToStaticMarkup(createElement(Welcome, { bench, projects: ["demo"], exampleProject: "demo" }));
  assert.match(html, /Welcome to NOHARM/);
  assert.match(html, /<a[^>]*data-recommended="true"[^>]*href="\/noharm\/tutorial"[^>]*>Start walkthrough</);
  assert.match(html, /<button[^>]*aria-haspopup="dialog"[^>]*>Create project<\/button>/);
  assert.doesNotMatch(html, />Resume project<\/button>|Manage projects|Replay walkthrough/);
});

test("resume dialog selects the project and restores its mode", () => {
  const { root } = buildFixture();
  const bench = loadBenchmark(root, CASESET);
  const html = renderToStaticMarkup(createElement(Welcome, { bench, projects: ["demo", CASESET], exampleProject: "demo", mode: "resume", projectModes: { [CASESET]: "local" } }));
  assert.match(html, /<dialog[^>]*aria-labelledby="resume-project-title"/);
  assert.ok(pane(html, "Learn NOHARMKit"));
  assert.ok(pane(html, "Get started"));
  assert.match(html, /action="\/api\/benchmark"/);
  assert.match(html, /name="returnTo" value="\/noharm\/dashboard"/);
  assert.ok(html.includes(`<option value="${CASESET}" selected="">`));
  assert.doesNotMatch(html, /<option value="demo"/);
  assert.match(html.match(/<input[^>]*id="resume-project-mode-local"[^>]*>/)?.[0] ?? "", /checked=""/);
  assert.doesNotMatch(html.match(/<input[^>]*id="resume-project-mode-api"[^>]*>/)?.[0] ?? "", /checked=""/);
  assert.match(html.match(/<input[^>]*id="new-project-mode-api"[^>]*>/)?.[0] ?? "", /checked=""/);
  assert.match(html, /name="execution_mode"/);
});

test("new project uses the approved name and mode modal over the welcome page", () => {
  const { root } = buildFixture();
  const html = renderToStaticMarkup(createElement(Welcome, { bench: loadBenchmark(root, CASESET), mode: "new" }));
  assert.match(html, /<dialog[^>]*aria-labelledby="new-project-title"/);
  assert.ok(pane(html, "Learn NOHARMKit"));
  assert.ok(pane(html, "Get started"));
  assert.match(html, /id="new-project-name"/);
  assert.doesNotMatch(html, /id="new-project-idea"|Benchmark idea/);
  const pattern = html.match(/<input[^>]*id="new-project-name"[^>]*pattern="([^"]+)"/)?.[1];
  assert.ok(pattern);
  const validName = new RegExp(`^(?:${pattern})$`, "v");
  assert.equal(validName.test("vascular-surgery"), true);
  for (const name of ["Invalid name", "-project", "../bad"]) assert.equal(validName.test(name), false);
  assert.match(html, /<legend>Mode<\/legend>/);
  assert.match(html, /Use OpenRouter API credits to drive the pipeline/);
  assert.match(html, /Use your local coding agent \(Claude Code, Codex, etc\) to drive the pipeline/);
  assert.match(html.match(/<input[^>]*id="new-project-mode-api"[^>]*>/)?.[0] ?? "", /checked=""/);
  assert.doesNotMatch(html, /Interface preview|Project mode review|Nothing was saved/);
});

test("a non-synthetic project named demo stays resumable", () => {
  const { root } = buildFixture();
  const loaded = loadBenchmark(root, CASESET);
  const bench = { ...loaded, name: "demo", cases: loaded.cases.map((c) => ({ ...c, page: { ...c.page, provenance: { ...c.page.provenance, synthetic: false } } })) };
  const html = renderToStaticMarkup(createElement(Welcome, { bench, exampleProject: "demo" }));
  assert.ok(pane(html, "Learn NOHARMKit"));
  assert.match(html, /<option value="demo" selected="">/);
  assert.deepEqual(resumableProjects(["demo", "tutorial-123", "vascular"], "demo"), ["tutorial-123", "vascular"]);
});

const TUTORIAL_NAME = "tutorial-e79e2181-7133-48c6-958c-f167f9f9f3dc";
const COMPLETION_CASES: { label: string; bench: (bench: Benchmark) => Benchmark; complete: boolean }[] = [
  { label: "scored tutorial offers independent creation", bench: bench => ({ ...bench, name: TUTORIAL_NAME, models: [MODEL_A] }), complete: true },
  { label: "ordinary project", bench: bench => bench, complete: false },
  { label: "empty tutorial", bench: bench => ({ ...bench, name: TUTORIAL_NAME, cases: [], models: [] }), complete: false },
  { label: "partially scored tutorial", bench: bench => ({ ...bench, name: TUTORIAL_NAME }), complete: false },
];

test("walkthrough completion appears only for a scored tutorial", () => eachCase(COMPLETION_CASES, (c) => c.label, (c) => {
  const { root } = buildFixture();
  const html = renderToStaticMarkup(createElement(Leaderboard, { bench: c.bench(loadBenchmark(root, CASESET)) }));
  if (c.complete) {
    assert.match(html, /Your walkthrough is complete/);
    assert.match(html, /href="\/noharm\/welcome\?mode=new"/);
  } else assert.doesNotMatch(html, /Your walkthrough is complete/);
}));

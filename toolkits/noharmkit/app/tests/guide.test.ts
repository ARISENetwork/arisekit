import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Guide from "../components/mc/Guide";
import { stepHref } from "../lib/caseset/routes";
import { STEP_KEYS } from "../lib/caseset/steps";

test("the guide works before a project exists, names its pipeline overview, and hides inactive step details", () => {
  const html = renderToStaticMarkup(createElement(Guide));
  assert.ok(html.includes('href="/noharm/welcome?mode=new"'));
  assert.ok(html.includes("my-benchmark"));
  assert.ok(!html.includes("View demo"));
  assert.ok(html.includes("Copying a prompt does not run it."));
  for (const step of STEP_KEYS) assert.ok(html.includes(`href="${stepHref(step)}"`));
  assert.match(html, /<section(?=[^>]*aria-labelledby="guide-pipeline-overview")[^>]*>/);
  assert.match(html, /<h2(?=[^>]*id="guide-pipeline-overview")[^>]*>Pipeline Overview<\/h2>/);
  assert.ok(html.includes("Six pipeline steps, from Dataset to Leaderboard"));
  for (const step of STEP_KEYS) {
    assert.match(html, new RegExp(`<button(?=[^>]*aria-controls="guide-step-${step}")(?=[^>]*aria-pressed="${step === "cases"}")[^>]*>`));
    if (step !== "cases") assert.match(html, new RegExp(`<div(?=[^>]*id="guide-step-${step}")(?=[^>]*aria-hidden="true")(?=[^>]*inert="")[^>]*>`));
  }
  assert.ok(html.includes("Task and Solution must be nonempty"));
});

test("the guide scopes prompts to the current project and links to the tutorial", () => {
  const html = renderToStaticMarkup(createElement(Guide, { benchmark: "blank-project" }));
  assert.ok(html.includes("Use noharm for project &quot;blank-project&quot;."));
  assert.ok(html.includes('href="/noharm/tutorial"'));
  assert.ok(html.includes('href="/noharm/framework"'));
  assert.ok(html.includes("View Tutorial"));
  assert.doesNotMatch(html, /synthetic demo|Walk through the demo|View demo|bundled demo|Demo001/i);
  assert.ok(html.includes("Saving a reviewed rubric does not update existing judgments."));
});

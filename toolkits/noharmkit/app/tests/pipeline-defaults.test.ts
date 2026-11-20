import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { DEFAULT_JUDGE, openRouterId } from "../lib/pipeline-defaults";

test("the app's default judge is the command line's default judge, at the same effort", () => {
  const shared = JSON.parse(readFileSync(new URL("../../pipeline/e2e/pipeline_v2_defaults.json", import.meta.url), "utf8"));
  assert.equal(DEFAULT_JUDGE.model, openRouterId(shared.judge));
  assert.equal(DEFAULT_JUDGE.reasoning, shared.judge.reasoning_effort);
});

test("routes map to OpenRouter IDs, and an unmapped route fails loudly", () => {
  assert.equal(openRouterId({ backend: "openai", model: "gpt-6.1-sol" }), "openai/gpt-6.1-sol");
  assert.equal(openRouterId({ backend: "openrouter", model: "anthropic/claude-opus-5.5" }), "anthropic/claude-opus-5.5");
  assert.throws(() => openRouterId({ backend: "claude", model: "claude-opus-5-5" }), /No OpenRouter model ID/);
});

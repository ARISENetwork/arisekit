import assert from "node:assert/strict";
import test from "node:test";
import { apiResponseRoute, responseModelIdentity, responseSettingsDifference } from "../lib/response-settings";
import type { ResponseRoute } from "../lib/caseset/types";
import { eachCase } from "./cases";

test("response identities keep filename normalization and the default route has no parameters", () => {
  assert.equal(responseModelIdentity("provider/model:preview"), "provider-model-preview");
  assert.deepEqual(apiResponseRoute("provider/model"), { backend: "openrouter", model: "provider/model", kwargs: {} });
});

const preview = apiResponseRoute("provider/model:preview", "low");
const defaults = apiResponseRoute("provider/model");
const retained: ResponseRoute = { ...apiResponseRoute("provider/model", "low"), kwargs: { temperature: 0, reasoning_effort: "low" } };
const legacyNull: ResponseRoute = { ...defaults, kwargs: { reasoning_effort: null } };
const DIFFERENCE_CASES: { label: string; stored: ResponseRoute; desired: ResponseRoute; policy: "all" | "reasoning"; expected: ReturnType<typeof responseSettingsDifference> }[] = [
  { label: "normalized identity is a different route", stored: { ...preview, model: "provider/model-preview" }, desired: preview, policy: "all", expected: "route" },
  { label: "another backend is a different route", stored: { ...preview, backend: "codex" }, desired: preview, policy: "reasoning", expected: "route" },
  ...(["all", "reasoning"] as const).flatMap(policy => (["none", "low", "high"] as const).flatMap(effort => [
    { label: `explicit ${effort} versus Model default (${policy})`, stored: apiResponseRoute("provider/model", effort), desired: defaults, policy, expected: "parameters" as const },
    { label: `explicit ${effort} versus explicit ${effort} (${policy})`, stored: apiResponseRoute("provider/model", effort), desired: apiResponseRoute("provider/model", effort), policy, expected: null },
  ])),
  { label: "extra parameter is bound for saves", stored: retained, desired: apiResponseRoute("provider/model", "low"), policy: "all", expected: "parameters" },
  { label: "extra parameter is ignored by legacy coverage", stored: retained, desired: apiResponseRoute("provider/model", "low"), policy: "reasoning", expected: null },
  { label: "parameter order does not matter", stored: retained, desired: { ...retained, kwargs: { reasoning_effort: "low", temperature: 0 } }, policy: "all", expected: null },
  { label: "legacy null reasoning equals Model default for coverage", stored: legacyNull, desired: defaults, policy: "reasoning", expected: null },
  { label: "legacy null reasoning stays bound for saves", stored: legacyNull, desired: defaults, policy: "all", expected: "parameters" },
];

test("responseSettingsDifference", () => eachCase(DIFFERENCE_CASES, (c) => c.label, (c) => {
  const before = structuredClone(c.stored);
  assert.equal(responseSettingsDifference(c.stored, c.desired, c.policy), c.expected);
  assert.deepEqual(c.stored, before);
}));

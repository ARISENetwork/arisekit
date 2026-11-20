import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { deletePrompt, loadPrompts, promptId, savePrompt, usedPromptIds } from "../lib/response-prompts";
import { eachCase } from "./cases";

const LOCKED = "This prompt has collected responses. Save your changes as a new prompt.";

function workspace(provenance: object = {}, project = "p"): { root: string; file: string } {
  const root = mkdtempSync(path.join(os.tmpdir(), "noharm-prompts-"));
  mkdirSync(path.join(root, project));
  writeFileSync(path.join(root, project, "provenance.json"), JSON.stringify(provenance));
  return { root, file: path.join(root, project, "prompts.json") };
}

test("prompt ids follow the Python slug rule", () => {
  assert.equal(promptId("Safety first!"), "safety-first");
  assert.equal(promptId("  Step  by step "), "step-by-step");
});

test("saving stores trimmed text with its sha256 and lists it back", () => {
  const { root, file } = workspace();
  assert.deepEqual(loadPrompts(root, "p"), []);
  const saved = savePrompt(root, "p", { name: "Safety first", text: "  Think safely.  " });
  assert.equal(saved.id, "safety-first");
  assert.equal(saved.text, "Think safely.");
  assert.equal(saved.sha256, createHash("sha256").update("Think safely.", "utf8").digest("hex"));
  assert.deepEqual(loadPrompts(root, "p"), [saved]);
  assert.equal(JSON.parse(readFileSync(file, "utf8")).version, 1);
});

const REFUSALS: { label: string; project?: string; provenance?: object; existing?: { name: string; text: string }; input: { name: string; text: string }; error: RegExp }[] = [
  { label: "blank text", input: { name: "A", text: "   " }, error: /Prompt text/ },
  { label: "empty name", input: { name: "", text: "x" }, error: /name/ },
  { label: "name without letters or digits", input: { name: "!!!", text: "x" }, error: /name/ },
  { label: "name over 64 characters", input: { name: "n".repeat(65), text: "x" }, error: /name/ },
  { label: "text over 20000 characters", input: { name: "A", text: "x".repeat(20001) }, error: /Prompt text/ },
  { label: "duplicate name", existing: { name: "Safety first", text: "x" }, input: { name: "safety FIRST", text: "y" }, error: /already exists/ },
  { label: "the prepared demo", project: "demo", provenance: { synthetic: true }, input: { name: "A", text: "x" }, error: /The prepared demo is read-only/ },
];

test("prompt saves are refused for invalid input and the prepared demo", () => eachCase(REFUSALS, (c) => c.label, (c) => {
  const project = c.project ?? "p";
  const { root } = workspace(c.provenance, project);
  if (c.existing) savePrompt(root, project, c.existing);
  assert.throws(() => savePrompt(root, project, c.input), c.error);
}));

test("an unused prompt can be edited or deleted", () => {
  const { root } = workspace();
  savePrompt(root, "p", { name: "One", text: "a" });
  const edited = savePrompt(root, "p", { name: "One", text: "b", replaces: "one" });
  assert.equal(loadPrompts(root, "p")[0].text, "b");
  const renamed = savePrompt(root, "p", { name: "Two", text: "b", replaces: edited.id });
  assert.deepEqual(loadPrompts(root, "p").map(p => p.id), ["two"]);
  deletePrompt(root, "p", renamed.id);
  assert.deepEqual(loadPrompts(root, "p"), []);
});

function configured(root: string, project: string, prompts: string[]): void {
  writeFileSync(path.join(root, project, "api-pipeline.json"), JSON.stringify({ version: 2, teams: { generation: { models: ["t/w"], integrator: "" }, rating: { models: [], integrator: "" }, responses: { models: ["t/s"], integrator: "", prompts }, judge: { models: ["t/j"], integrator: "" } } }));
}

const LOCK_CASES: { label: string; provenance: object; setup: (root: string) => void; refusals: ((root: string) => unknown)[]; after?: (root: string) => void }[] = [
  {
    label: "recorded in provenance set_prompts",
    provenance: { inference: { set_prompts: { "m+one": { id: "one", name: "One", sha256: "x" } } } },
    setup: root => { savePrompt(root, "p", { name: "One", text: "a" }); },
    refusals: [root => savePrompt(root, "p", { name: "One", text: "b", replaces: "one" }), root => deletePrompt(root, "p", "one")],
  },
  {
    label: "listed in api-pipeline.json but not yet recorded",
    provenance: {},
    setup: root => {
      savePrompt(root, "p", { name: "One", text: "a" });
      savePrompt(root, "p", { name: "Two", text: "b" });
      configured(root, "p", ["one"]);
    },
    refusals: [
      root => deletePrompt(root, "p", "one"),
      root => savePrompt(root, "p", { name: "One", text: "changed", replaces: "one" }),
      root => savePrompt(root, "p", { name: "Uno", text: "a", replaces: "one" }),
    ],
    after: root => {
      savePrompt(root, "p", { name: "One", text: "a", replaces: "one" });
      deletePrompt(root, "p", "two");
    },
  },
];

test("prompts in use are locked and the file is untouched", () => eachCase(LOCK_CASES, (c) => c.label, (c) => {
  const { root, file } = workspace(c.provenance);
  c.setup(root);
  const before = readFileSync(file);
  assert.deepEqual([...usedPromptIds(root, "p")], ["one"]);
  for (const refuse of c.refusals) assert.throws(() => refuse(root), new RegExp(LOCKED));
  assert.deepEqual(readFileSync(file), before);
  c.after?.(root);
}));

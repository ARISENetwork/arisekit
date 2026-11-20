import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { emptyDatasetDrafts } from "../lib/dataset-draft-state";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const PendingDataset: typeof import("../components/mc/PendingDataset").default = require("../components/mc/PendingDataset").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const draftPath = "/tmp/projects/example/drafts/dataset.json";
const sourcePath = "/tmp/projects/example/imports/upload/Case001.json";
const ready = { id: "Case001", task: "Saved task", solutions: ["Saved solution"], errors: "Supplied error" };
const props = { project: "example", drafts: emptyDatasetDrafts(), draftPath, sources: [] };

function render(value: Parameters<typeof PendingDataset>[0]): string {
  return renderToStaticMarkup(createElement(PendingDataset, value));
}

const STATE_CASES: { label: string; value: Parameters<typeof PendingDataset>[0]; match: RegExp[]; absent: RegExp[] }[] = [
  {
    label: "an untouched project directs the user to Dataset without inventing an import source", value: props,
    match: [/No cases imported/, /Add a Task and Solution/, /href="\/noharm\/dataset"/], absent: [/Copy Prompt|dataset is saved|noharm-import-cases/],
  },
  {
    label: "incomplete drafts remain saved but do not produce an invalid import prompt",
    value: { ...props, drafts: { ...emptyDatasetDrafts(), drafts: { partial: { ...ready, solutions: ["", "Alternative"] } } } },
    match: [/A saved draft still needs a Task and Solution/], absent: [/Copy Prompt|noharm-import-cases/],
  },
  {
    label: "an unfinished alternative does not block a draft with a Task and primary Solution",
    value: { ...props, drafts: { ...emptyDatasetDrafts(), drafts: { ready: { ...ready, solutions: ["Saved solution", ""] } } } },
    match: [/Copy Prompt/], absent: [],
  },
  {
    label: "processed uploads are not offered again and blank drafts are not pending",
    value: { ...props, drafts: { ...emptyDatasetDrafts(), drafts: { new: { task: "", solutions: [""], errors: "" } } }, sources: [{ filename: "processed.json", path: sourcePath, processed: true }] },
    match: [/No cases imported/], absent: [/processed.json|Copy Prompt|Dataset awaiting import/],
  },
];

test("pending dataset states", () => eachCase(STATE_CASES, (c) => c.label, (c) => {
  const html = render(c.value);
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
}));

test("a complete saved draft produces a handoff for its exact project, file, and draft key", () => {
  const value = { ...props, drafts: { ...emptyDatasetDrafts(), selected: "new:Case001", drafts: { "new:Case001": ready } } };
  const before = JSON.stringify(value);
  const html = render(value);
  assert.match(html, /Dataset awaiting import/);
  assert.match(html, /no cases have been imported yet/);
  assert.ok(html.includes("drafts[&quot;new:Case001&quot;]"));
  assert.ok(html.includes(draftPath));
  assert.ok(html.includes('project &quot;example&quot;'));
  assert.match(html, /Import only that draft/);
  assert.match(html, /Do not import other drafts or replace existing cases/);
  assert.match(html, /Copy Prompt/);
  assert.equal(JSON.stringify(value), before);
});

test("pending uploads name their real source and do not duplicate draft import instructions", () => {
  const html = render({ ...props,
    drafts: { ...emptyDatasetDrafts(), drafts: { new: ready } },
    sources: [{ filename: "Case001.json", path: sourcePath, processed: false }],
  });
  assert.match(html, /Case001.json/);
  assert.ok(html.includes(sourcePath));
  assert.match(html, /noharm-import-cases and noharm-rubrics/);
  assert.match(html, /saved drafts are also available in Dataset/);
  assert.doesNotMatch(html, /Read the saved dataset draft at drafts/);
  assert.equal((html.match(/>Copy Prompt<\/button>/g) ?? []).length, 1);
});


import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { GET, POST } from "../app/api/dataset-drafts/route";
import { DatasetDraftConflict, readDatasetDrafts, saveDatasetDrafts } from "../lib/dataset-drafts";
import { createDatasetDraftSaver, type DraftSaveStatus } from "../lib/dataset-draft-saver";
import { emptyDatasetDrafts, type DatasetDraftState } from "../lib/dataset-draft-state";
import { eachCase } from "./cases";

function fixture(): { root: string; dir: string } {
  const root = mkdtempSync(path.join(os.tmpdir(), "dataset-drafts-"));
  const dir = path.join(root, "test");
  mkdirSync(path.join(dir, "cases"), { recursive: true });
  writeFileSync(path.join(dir, "cases/Case001.json"), '{"presentation":"Imported task","recommendations":"Imported answer","errors":"Supplied error"}\n');
  writeFileSync(path.join(dir, "items.jsonl"), '{"id":"Case001","prompt":"Imported task"}\n');
  writeFileSync(path.join(dir, "provenance.json"), '{"caseset_name":"test","source":"user supplied","trials":1}\n');
  return { root, dir };
}

function state(revision = 0): DatasetDraftState {
  return {
    revision,
    selected: "draft-2",
    drafts: {
      "draft-1": { id: "Case002", task: "  Partly entered task\n", solutions: ["", " An independent alternative\n"], errors: "- Moderate: supplied error\n" },
      "draft-2": { source_item_id: "Case001", task: "", solutions: ["  First answer  ", ""], errors: "" },
    },
    bases: { "draft-2": { task: "Imported task", solutions: ["Imported answer"], errors: "Supplied error" } },
  };
}

test("draft lifecycle", () => {
  // Unsaved projects start empty without creating a draft file.
  const { root, dir } = fixture();
  assert.deepEqual(readDatasetDrafts(root, "test"), { revision: 0, selected: null, drafts: {}, bases: {} });
  assert.equal(existsSync(path.join(dir, "drafts/dataset.json")), false);
  // Round trips multiple incomplete cases, exact source text, alternatives, selection, and edit bases.
  const original = ["cases/Case001.json", "items.jsonl", "provenance.json"].map((file) => readFileSync(path.join(dir, file)));
  const expected = { ...state(), revision: 1 };
  assert.deepEqual(saveDatasetDrafts(root, "test", state()), expected);
  assert.deepEqual(readDatasetDrafts(root, "test"), expected);
  assert.deepEqual(JSON.parse(readFileSync(path.join(dir, "drafts/dataset.json"), "utf8")), expected);
  ["cases/Case001.json", "items.jsonl", "provenance.json"].forEach((file, index) => assert.deepEqual(readFileSync(path.join(dir, file)), original[index]));
  assert.deepEqual(readdirSync(path.join(dir, "cases")), ["Case001.json"]);
  mkdirSync(path.join(root, "other"));
  assert.deepEqual(readDatasetDrafts(root, "other"), { revision: 0, selected: null, drafts: {}, bases: {} });
  assert.equal(existsSync(path.join(root, "other/drafts")), false);
  // Clearing drafts persists a new revision without changing imported records.
  const cleared = { revision: 1, selected: null, drafts: {}, bases: {} };
  assert.deepEqual(saveDatasetDrafts(root, "test", cleared), { ...cleared, revision: 2 });
  assert.deepEqual(readDatasetDrafts(root, "test"), { ...cleared, revision: 2 });
  assert.equal(readdirSync(path.join(dir, "cases")).length, 1);
});

test("malformed draft saves cannot replace the last valid draft", () => {
  const { root, dir } = fixture();
  saveDatasetDrafts(root, "test", state());
  const file = path.join(dir, "drafts/dataset.json");
  const saved = readFileSync(file);
  const invalid: unknown[] = [
    { ...state(1), revision: -1 },
    { ...state(1), selected: 42 },
    { ...state(1), drafts: { broken: { task: 42, solutions: [""], errors: "" } } },
    { ...state(1), drafts: { broken: { task: "", solutions: [], errors: "" } } },
    { ...state(1), bases: { "draft-2": { task: "", solutions: [null], errors: "" } } },
  ];
  for (const value of invalid) {
    assert.throws(() => saveDatasetDrafts(root, "test", value));
    assert.deepEqual(readFileSync(file), saved);
  }
});

test("a stale browser cannot overwrite another browser's newer draft", () => {
  const { root, dir } = fixture();
  const first = saveDatasetDrafts(root, "test", state());
  const newest = saveDatasetDrafts(root, "test", { ...first, drafts: { ...first.drafts, "draft-1": { ...first.drafts["draft-1"], task: "Newer browser text" } } });
  const saved = readFileSync(path.join(dir, "drafts/dataset.json"));
  assert.throws(() => saveDatasetDrafts(root, "test", { ...first, selected: "draft-1" }), DatasetDraftConflict);
  assert.deepEqual(readFileSync(path.join(dir, "drafts/dataset.json")), saved);
  assert.deepEqual(readDatasetDrafts(root, "test"), newest);
});

// Each plant returns the project name to read and save. Drafts require an existing project and never follow a link out of project storage.
const CONTAINMENT: Array<{ name: string; plant: (root: string, dir: string, outside: string) => string }> = [
  { name: "missing project", plant: () => "missing" },
  { name: "drafts folder linked outside", plant: (_root, dir, outside) => { symlinkSync(outside, path.join(dir, "drafts")); return "test"; } },
  { name: "project folder linked outside", plant: (root, _dir, outside) => { symlinkSync(outside, path.join(root, "linked-project")); return "linked-project"; } },
  { name: "draft file linked outside", plant: (_root, dir, outside) => {
    mkdirSync(path.join(dir, "drafts"));
    symlinkSync(path.join(outside, "dataset.json"), path.join(dir, "drafts/dataset.json"));
    return "test";
  } },
];

test("draft storage containment", () => eachCase(CONTAINMENT, (c) => c.name, (c) => {
  const { root, dir } = fixture();
  const outside = mkdtempSync(path.join(os.tmpdir(), "dataset-drafts-outside-"));
  writeFileSync(path.join(outside, "dataset.json"), "outside sentinel");
  const project = c.plant(root, dir, outside);
  assert.throws(() => readDatasetDrafts(root, project));
  assert.throws(() => saveDatasetDrafts(root, project, state()));
  assert.equal(readFileSync(path.join(outside, "dataset.json"), "utf8"), "outside sentinel");
  if (project === "missing") assert.equal(existsSync(path.join(root, "missing")), false);
}));

test("draft API loads and saves project state, rejects foreign mutations and malformed requests, and reports conflicts", async () => {
  const { root, dir } = fixture();
  const previous = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = root;
  const get = (query: string): NextRequest => new NextRequest(`http://localhost/api/dataset-drafts${query}`);
  const post = (body: string, origin = "http://localhost"): NextRequest => new NextRequest("http://localhost/api/dataset-drafts", { method: "POST", headers: { origin, "Content-Type": "application/json" }, body });
  try {
    const empty = await GET(get("?project=test"));
    assert.equal(empty.status, 200);
    assert.deepEqual(await empty.json(), { revision: 0, selected: null, drafts: {}, bases: {} });
    assert.equal((await GET(get(""))).status, 400);
    assert.equal((await GET(get("?project=missing"))).status, 404);
    const body = JSON.stringify({ project: "test", state: state() });
    assert.equal((await POST(post(body, "https://other.example"))).status, 403);
    assert.equal(existsSync(path.join(dir, "drafts/dataset.json")), false);
    const saved = await POST(post(body));
    assert.equal(saved.status, 200);
    assert.deepEqual(await saved.json(), { ...state(), revision: 1 });
    assert.deepEqual(await (await GET(get("?project=test"))).json(), { ...state(), revision: 1 });
    const original = readFileSync(path.join(dir, "drafts/dataset.json"));
    assert.equal((await POST(post(body))).status, 409);
    assert.equal((await POST(post("{"))).status, 400);
    assert.equal((await POST(post(JSON.stringify({ project: "test", state: { ...state(1), drafts: [] } })))).status, 400);
    assert.equal((await POST(post(JSON.stringify({ project: "missing", state: state() })))).status, 404);
    assert.deepEqual(readFileSync(path.join(dir, "drafts/dataset.json")), original);
  } finally {
    if (previous === undefined) delete process.env.NOHARM_PROJECTS;
    else process.env.NOHARM_PROJECTS = previous;
  }
});

test("navigation flush waits for the latest edit and serializes revisioned saves", async () => {
  let release!: (revision: number) => void;
  const first = new Promise<number>((resolve) => { release = resolve; });
  const sent: { revision: number; task: string }[] = [];
  const statuses: DraftSaveStatus[] = [];
  const saver = createDatasetDraftSaver(3, async (state) => {
    sent.push({ revision: state.revision, task: state.drafts.new.task });
    return sent.length === 1 ? first : state.revision + 1;
  }, (status) => statuses.push(status));
  const draft = (task: string) => ({ ...emptyDatasetDrafts(), selected: "new", drafts: { new: { task, solutions: [""], errors: "" } } });
  saver.enqueue(draft("First edit"));
  saver.enqueue(draft("Second edit"));
  saver.enqueue(draft("Final edit"));
  assert.equal(saver.pending(), true);
  let navigated = false;
  const navigation = saver.flush().then((saved) => { navigated = saved; });
  assert.equal(navigated, false);
  release(4);
  await navigation;
  assert.equal(navigated, true);
  assert.deepEqual(sent, [{ revision: 3, task: "First edit" }, { revision: 4, task: "Final edit" }]);
  assert.equal(saver.pending(), false);
  assert.deepEqual(statuses, [{ state: "saving" }, { state: "saved" }]);
});

test("failed saves retain the latest text, block navigation, and retry at the uncommitted revision", async () => {
  let reject!: (error: Error) => void;
  const failed = new Promise<number>((_, fail) => { reject = fail; });
  const sent: string[] = [];
  const revisions: number[] = [];
  const statuses: DraftSaveStatus[] = [];
  const saver = createDatasetDraftSaver(2, async (state) => {
    sent.push(state.drafts.new.task); revisions.push(state.revision);
    return sent.length === 1 ? failed : state.revision + 1;
  }, (status) => statuses.push(status));
  const draft = (task: string) => ({ ...emptyDatasetDrafts(), drafts: { new: { task, solutions: [""], errors: "" } } });
  saver.enqueue(draft("Initial text"));
  saver.enqueue(draft("Latest text"));
  const navigation = saver.flush();
  reject(new Error("Network disconnected"));
  assert.equal(await navigation, false);
  assert.equal(saver.pending(), true);
  assert.deepEqual(statuses.at(-1), { state: "error", error: "Network disconnected" });
  assert.equal(await saver.flush(), true);
  assert.deepEqual(sent, ["Initial text", "Latest text"]);
  assert.deepEqual(revisions, [2, 2]);
  assert.equal(saver.pending(), false);
});

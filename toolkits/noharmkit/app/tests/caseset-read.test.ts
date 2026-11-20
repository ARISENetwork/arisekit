import assert from "node:assert/strict";
import fs, { mkdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import path from "node:path";
import test from "node:test";

import { pythonJsonDumps, tableSha256 } from "../lib/caseset/hash";
import { buildLeaderboard } from "../lib/caseset/leaderboard";
import { loadBenchmark } from "../lib/caseset/metrics";
import { assertCase, casesetDir, inside, NotFoundError, parseVersion } from "../lib/caseset/paths";
import { disagreementCount, listCasesets, loadCasePage, loadLens, loadTableVersion, readJsonl, withJsonlReadCache } from "../lib/caseset/read";
import type { ResponseRow } from "../lib/caseset/types";
import { eachCase } from "./cases";
import { buildFixture, CASESET, MODEL_A, MODEL_B, relink, RESPONSE, TABLE, writeCasesetFile } from "./caseset-fixture";

// Generated with Python: for each value, json.dumps(value, sort_keys=True) and its sha256 (the table_sha256 recipe).
const PARITY: Array<{ value: unknown; dumps: string; sha: string }> = [
  { value: {"b": [1, true, null, {"y": "\u00e9", "x": 0}], "a": "\u2265 2\u20133 \"q\"\n\t\u007f", "c": {"z": -4, "D10": "s", "D2": "t"}}, dumps: "{\"a\": \"\\u2265 2\\u20133 \\\"q\\\"\\n\\t\\u007f\", \"b\": [1, true, null, {\"x\": 0, \"y\": \"\\u00e9\"}], \"c\": {\"D10\": \"s\", \"D2\": \"t\", \"z\": -4}}", sha: "e9e689d9649bb8b367cdc52c0c5e45d169254eceae901956e437fc9af6e78c5f" },
  { value: {"z": {"b": [], "a": {}}, "B": "upper", "_": "under", "10": "ten", "9": "nine", "\u00e9": "e-acute", "a": [{"d": 1, "c": [2, {"f": null, "e": false}]}]}, dumps: "{\"10\": \"ten\", \"9\": \"nine\", \"B\": \"upper\", \"_\": \"under\", \"a\": [{\"c\": [2, {\"e\": false, \"f\": null}], \"d\": 1}], \"z\": {\"a\": {}, \"b\": []}, \"\\u00e9\": \"e-acute\"}", sha: "89d42b18554432bb3c61c8ed62745a63631d05664c7102eacfe63cf9d8e856c5" },
  { value: {"emoji": "\ud83d\ude00 ok", "cjk": "\u75c5\u4eba", "nbsp": "a\u00a0b", "ctrl": "\u0001\u001f", "slash": "a/b\\c", "sep": "\u2028"}, dumps: "{\"cjk\": \"\\u75c5\\u4eba\", \"ctrl\": \"\\u0001\\u001f\", \"emoji\": \"\\ud83d\\ude00 ok\", \"nbsp\": \"a\\u00a0b\", \"sep\": \"\\u2028\", \"slash\": \"a/b\\\\c\"}", sha: "f627d7a03123ce5f8c9bcc967303b307ab119891a86debdfcdc07bdb20dfb335" },
  { value: {"ints": [0, -1, 9007199254740991, -9007199254740991, 123456789]}, dumps: "{\"ints\": [0, -1, 9007199254740991, -9007199254740991, 123456789]}", sha: "26715498b385a2b814b0820154837d8f3b40d6382a3dfb68950917c6dd7612c5" },
];

test("pythonJsonDumps parity with Python and refusal outside its domain", () => {
  for (const { value, dumps, sha } of PARITY) {
    assert.equal(pythonJsonDumps(value), dumps);
    assert.equal(tableSha256(value), sha);
  }
  // Values outside the parity domain throw instead of hashing differently from Python.
  assert.throws(() => pythonJsonDumps({ x: 0.5 }), /only safe integers/);
  assert.throws(() => pythonJsonDumps({ x: 2 ** 53 }), /only safe integers/);
  assert.throws(() => pythonJsonDumps({ x: Number.NaN }), /only safe integers/);
  assert.throws(() => pythonJsonDumps([undefined]), /cannot hash/);
  assert.throws(() => pythonJsonDumps({ "\ud83d\ude00": 1 }), /Basic Multilingual Plane/);
});

test("caseset index", () => {
  // Casesets list with case counts and update time; files and symlinked folders are skipped.
  const { root } = buildFixture();
  assert.deepEqual(listCasesets(root), [
    { name: CASESET, answerTable: true, cases: 1, updatedAt: "2026-09-28T21:53:27+00:00", clinicianReviewed: false, provisional: true },
    { name: "legacy", answerTable: false, cases: 1, updatedAt: null, clinicianReviewed: false, provisional: false },
  ]);

  // The index marks a caseset clinician reviewed only when a reviewed copy has a passing status.
  const reviewedFile = { record: TABLE, basedOn: { version: "run1", sha256: tableSha256(TABLE) }, reviewer: "dwu", timing: {}, savedAt: "2026-09-28T22:00:00+00:00" };
  const cs = (fixture: ReturnType<typeof buildFixture>) => listCasesets(fixture.root).find((c) => c.name === CASESET)?.clinicianReviewed;
  const write = (fixture: ReturnType<typeof buildFixture>, name: string, body: unknown): void => writeFileSync(path.join(fixture.dir, "answer-tables", `Test002.${name}`), JSON.stringify(body));

  const missing = buildFixture();
  write(missing, "reviewed-dwu.json", reviewedFile);
  assert.equal(cs(missing), false);
  assert.equal(loadCasePage(missing.root, CASESET, "Test002").clinicianReviewed, false);

  const failed = buildFixture();
  write(failed, "reviewed-dwu.json", reviewedFile);
  write(failed, "reviewed-dwu.status.json", { status: "failed", errors: ["validator: x"] });
  assert.equal(cs(failed), false);

  const passed = buildFixture();
  write(passed, "reviewed-dwu.json", reviewedFile);
  write(passed, "reviewed-dwu.status.json", { status: "pass", errors: [] });
  assert.equal(cs(passed), true);
  assert.equal(loadCasePage(passed.root, CASESET, "Test002").clinicianReviewed, true);
});

test("case page and lens on the plain fixture", () => {
  // Table versions: project-owned runs, with status, ratings, errors, and raw output.
  const { root } = buildFixture();
  const page = loadCasePage(root, CASESET, "Test002");
  assert.deepEqual(page.tables.map((t) => [t.version, t.status]), [["run1", "pass"], ["run2", "failed"], ["run3", "pass"]]);
  const [run1, run2, run3] = page.tables;
  assert.equal(run1.sha256, tableSha256(TABLE));
  assert.equal(run1.record?.decisions.length, 2);
  assert.equal(disagreementCount(run1.ratings), 1);
  assert.equal(disagreementCount(run3.ratings), null);
  assert.deepEqual(run2.errors, ["validator: Usual care: rate its harm."]);
  assert.equal(run2.raw, "raw model output for run2");
  assert.equal(run3.record?.usualCare.harm, "severe");
  assert.equal(page.clinicianReviewed, false);
  assert.deepEqual(page.report?.gaps, ["openrouter-test-model-a: no response for [('Test002', 2)]"]);
  assert.match(page.commands.judge, /^\.venv\/bin\/python tools\/noharm\.py judge \S+cs1 --rubric run1$/);
  // Response rows: a retried error collapses, failed inference is not judged, a changed table is stale.
  const rows = loadCasePage(root, CASESET, "Test002").responses;
  assert.deepEqual(rows.map((r) => [r.model, r.trial, r.judge]), [[MODEL_A, 1, "pass"], [MODEL_A, 2, "no response"], [MODEL_B, 1, "stale"]]);
  assert.equal(rows[0].scored?.f1, 1);
  assert.equal(rows[0].scoreCheck, "current");
  assert.equal(rows[1].responseError, "timeout");
  assert.equal(rows[2].scored, null);
  // The lens joins a response, its judgment, the judged table, and its score.
  const lens = loadLens(root, CASESET, "Test002", MODEL_A, "1");
  assert.equal(lens.row.judge, "pass");
  assert.equal(lens.table?.version, "run1");
  assert.equal(lens.row.scored?.f1, 1);
  assert.equal(loadLens(root, CASESET, "Test002", MODEL_A, "2").row.judge, "no response");
});

// A score is shown only for the judgment, response and case it was computed from; when a response has two scored lines, the last one is used, like the judgment.
type ScoredLine = Record<string, unknown>;
const without = (line: ScoredLine, ...keys: string[]): ScoredLine => Object.fromEntries(Object.entries(line).filter(([key]) => !keys.includes(key)));
const SCORED_LINES: Array<{ name: string; lines: (current: ScoredLine) => ScoredLine[]; scoreCheck?: string; f1: number | null }> = [
  { name: "judgment hash changed", lines: (c) => [{ ...c, judgment_sha256: "0".repeat(64) }], scoreCheck: "mismatch", f1: null },
  { name: "rubric changed", lines: (c) => [{ ...c, rubric: "run2" }], scoreCheck: "mismatch", f1: null },
  { name: "response hash changed", lines: (c) => [{ ...c, response_sha256: "0".repeat(64) }], scoreCheck: "mismatch", f1: null },
  { name: "case hash changed", lines: (c) => [{ ...c, case_presentation_sha256: "0".repeat(64) }], scoreCheck: "mismatch", f1: null },
  { name: "legacy line without rubric and judgment hashes", lines: (c) => [without(c, "rubric_sha256", "judgment_sha256")], scoreCheck: "unverified", f1: 1 },
  { name: "legacy line without a response hash", lines: (c) => [without(c, "response_sha256")], scoreCheck: "unverified", f1: 1 },
  { name: "legacy line without a case hash", lines: (c) => [without(c, "case_presentation_sha256")], scoreCheck: "unverified", f1: 1 },
  { name: "two scored lines", lines: (c) => [{ ...c, f1: 0.25 }, { ...c, f1: 0.75 }], f1: 0.75 },
];

test("scored-line identity", () => eachCase(SCORED_LINES, (c) => c.name, (c) => {
  const { root, dir } = buildFixture();
  const scoredFile = path.join(dir, "results", `${MODEL_A}_scored.jsonl`);
  const current = JSON.parse(readFileSync(scoredFile, "utf8").trim()) as ScoredLine;
  writeFileSync(scoredFile, c.lines(current).map((line) => `${JSON.stringify(line)}\n`).join(""));
  const row: ResponseRow = loadCasePage(root, CASESET, "Test002").responses[0];
  if (c.scoreCheck !== undefined) assert.equal(row.scoreCheck, c.scoreCheck);
  if (c.f1 === null) assert.equal(row.scored, null);
  else assert.equal(row.scored?.f1, c.f1);
}));

test("changed response text, case text, or case identity hides old scores from the leaderboard", () => {
  for (const change of ["response", "case", "identity"] as const) {
    const f = buildFixture();
    if (change === "response") writeCasesetFile(f, `results/responses/${MODEL_A}.jsonl`, `${JSON.stringify({ id: "Test002", trial: 1, response: `${RESPONSE} Changed.` })}\n`);
    if (change === "case") writeCasesetFile(f, "cases/Test002.json", { presentation: "A changed case.", recommendations: "Preserved expert answer." });
    if (change === "identity") {
      const file = path.join(f.dir, "results", "judge", `${MODEL_A}.jsonl`);
      writeFileSync(file, `${JSON.stringify({ ...JSON.parse(readFileSync(file, "utf8")), caseId: "Test003" })}\n`);
    }
    const bench = loadBenchmark(f.root, CASESET);
    const row = bench.cases[0].responses.find((r) => r.row.model === MODEL_A && r.row.trial === 1)!;
    assert.equal(row.row.judge, "stale", change);
    assert.equal(row.row.scored, null, change);
    assert.equal(bench.meanF1.value, null, change);
    assert.equal(buildLeaderboard(bench).find((r) => r.model === MODEL_A)?.scored, 0, change);
  }
});

test("legacy judgments without exact input bindings stay inspectable and unverified without scores", () => {
  for (const absent of ["response_sha256", "case_presentation_sha256"] as const) {
    const f = buildFixture();
    const file = path.join(f.dir, "results", "judge", `${MODEL_A}.jsonl`);
    const record = JSON.parse(readFileSync(file, "utf8"));
    delete record[absent];
    writeFileSync(file, `${JSON.stringify(record)}\n`);
    const bench = loadBenchmark(f.root, CASESET);
    const row = bench.cases[0].responses[0].row;
    assert.equal(row.judge, "unverified", absent);
    assert.deepEqual(row.record?.judge, record.judge, absent);
    assert.equal(row.scored, null, absent);
    assert.equal(buildLeaderboard(bench).find((r) => r.model === MODEL_A)?.scored, 0, absent);
    assert.equal(bench.attention.find((r) => r.key === "unverifiedAutograding")?.count, 1, absent);
  }
});

test("duplicate successful responses or judgments cannot contribute to leaderboard scores", () => {
  for (const duplicate of ["response", "judgment"] as const) {
    const f = buildFixture();
    const file = path.join(f.dir, "results", duplicate === "response" ? "responses" : "judge", `${MODEL_A}.jsonl`);
    const lines = readFileSync(file, "utf8").trim().split("\n");
    const successful = lines.find((line) => { const row = JSON.parse(line); return duplicate === "response" ? row.response && !row.error : row.status === "pass"; })!;
    writeFileSync(file, `${lines.join("\n")}\n${successful}\n`);
    const bench = loadBenchmark(f.root, CASESET);
    const row = bench.cases[0].responses.find((r) => r.row.model === MODEL_A && r.row.trial === 1)!.row;
    assert.equal(row.scored, null, duplicate);
    assert.equal(bench.meanF1.value, null, duplicate);
    assert.equal(buildLeaderboard(bench).find((r) => r.model === MODEL_A)?.scored, 0, duplicate);
    if (duplicate === "response") assert.match(row.responseError ?? "", /Multiple successful responses/);
    else { assert.equal(row.judge, "failed"); assert.match(row.record?.errors.join(" ") ?? "", /Multiple successful judgments/); }
  }
});

test("path safety: traversal, absolute paths, symlinks, files, and unknown identifiers are refused", () => {
  const { root, dir } = buildFixture();
  for (const name of ["..", "../casesets", "/etc", "linked", "notes.txt", "missing", ""]) {
    assert.throws(() => casesetDir(root, name), NotFoundError, name);
  }
  for (const id of ["../Test002", "Test002/..", "Test003", "Test002-1"]) {
    assert.throws(() => assertCase(dir, id), NotFoundError, id);
  }
  for (const label of ["run4", "run0", "../run1", "reviewed-../x", "reviewed-dw", "latest", "/etc/passwd"]) {
    assert.throws(() => loadTableVersion(dir, "Test002", label), NotFoundError, label);
  }
  assert.throws(() => parseVersion("reviewed-D"), NotFoundError);
  assert.throws(() => inside(root, "..", "outside"), NotFoundError);
  assert.throws(() => inside(root, "linked", "cases"), NotFoundError);
  assert.throws(() => loadLens(root, CASESET, "Test002", "../../outside", "1"), NotFoundError);
  assert.throws(() => loadLens(root, CASESET, "Test002", MODEL_A, "1/../2"), NotFoundError);
  assert.throws(() => loadLens(root, CASESET, "Test002", MODEL_A, "9"), NotFoundError);
  assert.throws(() => loadLens(root, CASESET, "../Test002", MODEL_A, "1"), NotFoundError);
  // A dangling symlink is refused whether it points inside or outside the caseset.
  symlinkSync(path.join(dir, "does-not-exist"), path.join(dir, "dangling-inside"));
  symlinkSync(path.join(path.dirname(root), "nowhere"), path.join(dir, "dangling-outside"));
  assert.throws(() => inside(dir, "dangling-inside"), NotFoundError);
  assert.throws(() => inside(dir, "dangling-outside"), NotFoundError);
  assert.throws(() => inside(dir, "dangling-inside", "child.json"), NotFoundError);
});

test("a file or nested folder symlink that resolves outside the caseset is refused, never read", () => {
  const file = buildFixture();
  relink(path.join(file.outside, "cases", "Test002.json"), path.join(file.dir, "answer-tables", "Test002.run1.json"));
  assert.throws(() => loadTableVersion(file.dir, "Test002", "run1"), NotFoundError);
  assert.throws(() => loadCasePage(file.root, CASESET, "Test002"), NotFoundError);
  const folder = buildFixture();
  mkdirSync(path.join(folder.outside, "responses"));
  writeFileSync(path.join(folder.outside, "responses", `${MODEL_A}.jsonl`), "");
  relink(path.join(folder.outside, "responses"), path.join(folder.dir, "results", "responses"));
  assert.throws(() => loadCasePage(folder.root, CASESET, "Test002"), NotFoundError);
  assert.throws(() => inside(folder.dir, "results", "responses", "not-yet-written.jsonl"), NotFoundError);
});

test("a benchmark load reads each shared JSONL file once and preserves its result", (context) => {
  const fixture = buildFixture();
  writeCasesetFile(fixture, "cases/Test003.json", { presentation: "Second synthetic input", recommendations: "Second reference" });
  const expected = loadBenchmark(fixture.root, CASESET);
  const counts = new Map<string, number>();
  const readFile = fs.readFileSync;
  context.mock.method(fs, "readFileSync", (...args: Parameters<typeof fs.readFileSync>) => {
    const file = String(args[0]);
    if (file.endsWith(".jsonl")) counts.set(file, (counts.get(file) ?? 0) + 1);
    return readFile(...args);
  });
  syncBuiltinESMExports();
  try {
    assert.deepEqual(withJsonlReadCache(() => loadBenchmark(fixture.root, CASESET)), expected);
    assert.ok(counts.size > 1);
    assert.ok([...counts.values()].every((count) => count === 1));
  } finally {
    context.mock.restoreAll();
    syncBuiltinESMExports();
  }
});

test("overlapping loads keep their file snapshots independent", async () => {
  const fixture = buildFixture();
  const file = path.join(fixture.dir, "items.jsonl");
  const first = withJsonlReadCache(async () => {
    const rows = readJsonl(file);
    await Promise.resolve();
    assert.strictEqual(readJsonl(file), rows);
    return rows;
  });
  writeCasesetFile(fixture, "items.jsonl", '{"id":"Test003"}\n');
  const second = withJsonlReadCache(() => readJsonl<{ id: string }>(file));
  assert.deepEqual(second, [{ id: "Test003" }]);
  assert.notDeepEqual(await first, second);
  assert.deepEqual(readJsonl(file), second);
});

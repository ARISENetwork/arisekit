import assert from "node:assert/strict";
import test from "node:test";

import { buildLeaderboard } from "../lib/caseset/leaderboard";
import type { LeaderboardRow } from "../lib/caseset/leaderboard";
import { DEFAULT_SORT, nextLeaderboardSort, sortLeaderboard } from "../lib/caseset/leaderboard-sort";
import type { SortColumn, SortDirection } from "../lib/caseset/leaderboard-sort";
import { eachCase } from "./cases";

const row = (model: string, values: Partial<LeaderboardRow> = {}): LeaderboardRow => ({
  ...buildLeaderboard({ models: [model], cases: [] })[0], rank: null, ...values,
});
const models = (rows: LeaderboardRow[], column: SortColumn, direction: SortDirection): string[] =>
  sortLeaderboard(rows, { column, direction }).map((r) => r.model);

const SORTS: Array<{ label: string; column: SortColumn; rows: LeaderboardRow[]; ascending: string[]; descending: string[] }> = [
  ...(["rank", "f1", "recall", "precision"] as const).map((column) => ({
    label: `numeric ${column} sorts real values with missing metrics last`, column,
    rows: [row("missing"), row("high", { [column]: 0.9 }), row("zero", { [column]: 0 }), row("low", { [column]: 0.2 })],
    ascending: ["zero", "low", "high", "missing"], descending: ["high", "low", "zero", "missing"],
  })),
  { label: "model names sort naturally rather than treating model 10 as earlier than model 2", column: "model",
    rows: [row("Model 10"), row("model 2"), row("alpha")],
    ascending: ["alpha", "model 2", "Model 10"], descending: ["Model 10", "model 2", "alpha"] },
  { label: "severe harm sorts by the displayed rate, with unavailable harm last", column: "severe",
    rows: [
      row("higher rate", { scored: 2, harmCounts: { none: 0, uncertain: 0, mild: 0, moderate: 0, severe: 1 } }),
      row("lower rate", { scored: 20, harmCounts: { none: 0, uncertain: 0, mild: 0, moderate: 0, severe: 2 } }),
      row("unknown harm", { scored: 20, harmCounts: { none: 0, uncertain: 0, mild: 0, moderate: 0, severe: 2 }, unknownHarmCount: 1 }),
      row("unscored"),
    ],
    ascending: ["lower rate", "higher rate", "unknown harm", "unscored"], descending: ["higher rate", "lower rate", "unknown harm", "unscored"] },
  { label: "coverage sorts by fraction rather than the scored count", column: "coverage",
    rows: [row("more complete", { scored: 8, expected: 10 }), row("more responses", { scored: 9, expected: 30 }), row("empty")],
    ascending: ["more responses", "more complete", "empty"], descending: ["more complete", "more responses", "empty"] },
];

test("columns sort by their displayed values in both directions", () => eachCase(SORTS, (c) => c.label, (c) => {
  assert.deepEqual(models(c.rows, c.column, "ascending"), c.ascending);
  assert.deepEqual(models(c.rows, c.column, "descending"), c.descending);
}));

test("sorting preserves ties, source order, benchmark ranks, and score records", () => {
  const rows = [row("partial", { rank: 1, f1: 0.9 }), row("second", { rank: 2, f1: 0.5 }), row("first", { rank: 2, f1: 0.5 })];
  const before = JSON.stringify(rows);
  const sorted = sortLeaderboard(rows, { column: "f1", direction: "ascending" });
  assert.deepEqual(sorted.map((r) => [r.model, r.rank]), [["second", 2], ["first", 2], ["partial", 1]]);
  assert.equal(JSON.stringify(rows), before);
  assert.notEqual(sorted, rows);
});

test("repeated header selection toggles direction and new columns choose useful defaults", () => {
  assert.deepEqual(nextLeaderboardSort(DEFAULT_SORT, "f1"), { column: "f1", direction: "ascending" });
  assert.deepEqual(nextLeaderboardSort(nextLeaderboardSort(DEFAULT_SORT, "f1"), "f1"), DEFAULT_SORT);
  for (const column of ["rank", "model", "severe"] as const) {
    assert.deepEqual(nextLeaderboardSort(DEFAULT_SORT, column), { column, direction: "ascending" });
  }
  for (const column of ["recall", "precision", "coverage"] as const) {
    assert.deepEqual(nextLeaderboardSort(DEFAULT_SORT, column), { column, direction: "descending" });
  }
});

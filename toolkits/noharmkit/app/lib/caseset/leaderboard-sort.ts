import type { LeaderboardRow } from "./leaderboard";

export type SortColumn = "rank" | "model" | "f1" | "recall" | "precision" | "severe" | "coverage";
export type SortDirection = "ascending" | "descending";
export interface LeaderboardSort { column: SortColumn; direction: SortDirection }

export const DEFAULT_SORT: LeaderboardSort = { column: "f1", direction: "descending" };

export function nextLeaderboardSort(current: LeaderboardSort, column: SortColumn): LeaderboardSort {
  return {
    column,
    direction: current.column === column
      ? current.direction === "ascending" ? "descending" : "ascending"
      : column === "rank" || column === "model" || column === "severe" ? "ascending" : "descending",
  };
}

export function severeHarmRate(row: LeaderboardRow): number | null {
  return row.scored && !row.unknownHarmCount ? row.harmCounts.severe / row.scored : null;
}

function value(row: LeaderboardRow, column: SortColumn): number | string | null {
  switch (column) {
    case "severe": return severeHarmRate(row);
    case "coverage": return row.expected ? row.scored / row.expected : null;
    default: return row[column];
  }
}

// Sort display rows only. Missing values remain last in either direction; ties
// keep their original order and benchmark ranks are never recalculated.
export function sortLeaderboard(rows: readonly LeaderboardRow[], sort: LeaderboardSort): LeaderboardRow[] {
  return [...rows].sort((a, b) => {
    const left = value(a, sort.column);
    const right = value(b, sort.column);
    if (left === null) return right === null ? 0 : 1;
    if (right === null) return -1;
    const comparison = typeof left === "string" && typeof right === "string"
      ? left.localeCompare(right, "en", { numeric: true, sensitivity: "base" })
      : (left as number) - (right as number);
    return sort.direction === "ascending" ? comparison : -comparison;
  });
}

"use client";

import { useState } from "react";
import Link from "@/components/MotionLink";
import { fmt } from "@/components/mc/ui";
import type { LeaderboardRow } from "@/lib/caseset/leaderboard";
import { DEFAULT_SORT, nextLeaderboardSort, severeHarmRate, sortLeaderboard } from "@/lib/caseset/leaderboard-sort";
import type { SortColumn } from "@/lib/caseset/leaderboard-sort";
import { stepHref } from "@/lib/caseset/routes";
import styles from "./LeaderboardStep.module.css";

const COLUMNS: Array<{ key: SortColumn; label: string }> = [
  { key: "rank", label: "Rank" },
  { key: "model", label: "Model" },
  { key: "f1", label: "Mean F1" },
  { key: "recall", label: "Recall" },
  { key: "precision", label: "Precision" },
  { key: "severe", label: "Severe harm" },
  { key: "coverage", label: "Coverage" },
];

const rate = (row: LeaderboardRow): string => {
  const value = severeHarmRate(row);
  return value === null ? "-" : `${(100 * value).toFixed(1)}%`;
};

export default function LeaderboardTable({ rows, modelLabels = {} }: { rows: LeaderboardRow[]; modelLabels?: Record<string, string> }) {
  const [sort, setSort] = useState(DEFAULT_SORT);
  const orderedRows = sortLeaderboard(rows, sort);
  return (
    <div aria-label="Model leaderboard, scroll to see all columns" className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-mc-accent" role="region" tabIndex={0}>
      <table className={`w-full min-w-[860px] border-collapse text-[13px] ${styles.table}`}>
        <caption className="sr-only">Model performance across the benchmark</caption>
        <thead className="text-xs">
          <tr>
            {COLUMNS.map(({ key, label }) => {
              const active = sort.column === key;
              const next = nextLeaderboardSort(sort, key);
              return (
                <th
                  aria-sort={active ? sort.direction : undefined}
                  className={`${key === "rank" ? "px-5 text-left" : key === "model" ? "min-w-48 px-3 text-left" : "px-3 text-right"} py-3 font-semibold ${key === "f1" ? styles.scoreHeading : ""} ${active ? styles.sorted : ""}`}
                  key={key}
                  scope="col"
                >
                  <button aria-label={`Sort by ${label}, ${next.direction}`} className={styles.sortButton} onClick={() => setSort((current) => nextLeaderboardSort(current, key))} type="button">
                    {label}
                    <svg aria-hidden="true" className={styles.sortIcon} fill="none" height="12" viewBox="0 0 12 12" width="12">
                      {(!active || sort.direction === "ascending") && <path d="m3 4 3-3 3 3" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />}
                      {(!active || sort.direction === "descending") && <path d="m3 8 3 3 3-3" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />}
                    </svg>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {orderedRows.map((row) => (
            <tr className="border-t border-mc-line align-middle" key={row.model}>
              <td className="px-5 py-4 tabular-nums text-mc-muted"><span className={row.rank === null ? styles.unranked : styles.rank}>{row.rank ?? "-"}</span></td>
              <th className="px-3 py-4 text-left font-medium" scope="row">
                <Link className={styles.model} href={stepHref("scores", row.target ?? { model: row.model })}>{modelLabels[row.model] ?? row.model}</Link>
                <p className="m-0 mt-1 text-xs font-normal text-mc-muted">{row.scoredCases} of {row.totalCases} items scored</p>
                {(row.status !== "ranked" || row.draft || row.provisional) && <p className="m-0 mt-1 text-xs font-normal text-mc-muted">{[row.status === "not scored" && "Not scored", row.status === "partial" && "Partial coverage", row.unverified && "Unverified inputs", row.draft && "Draft", row.provisional && "Provisional"].filter(Boolean).join(", ")}</p>}
              </th>
              <td className={`px-3 py-4 text-right font-mc-mono tabular-nums ${styles.score}`}>
                <span className={styles.scoreValue}>{fmt(row.f1)}</span>
                {row.f1 !== null && <span aria-hidden="true" className={styles.scoreTrack}><span style={{ transform: `scaleX(${Math.min(1, Math.max(0, row.f1))})` }} /></span>}
              </td>
              <td className="px-3 py-4 text-right font-mc-mono tabular-nums">{fmt(row.recall)}</td>
              <td className="px-3 py-4 text-right font-mc-mono tabular-nums">{fmt(row.precision)}</td>
              <td className={`px-3 py-4 text-right font-mc-mono tabular-nums ${styles.severe}`}>{rate(row)}</td>
              <td className="px-3 py-4 text-right tabular-nums">
                <span className={`${styles.coverage} ${row.scored < row.expected ? styles.incomplete : ""}`}>
                  {row.scored} <span>/ {row.expected}</span>
                  {row.scored < row.expected && <span className="sr-only">, incomplete coverage</span>}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

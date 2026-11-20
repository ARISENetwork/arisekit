"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import Dropdown from "@/components/Dropdown";
import Link from "@/components/MotionLink";
import ScoreOutOfDate from "@/components/mc/ScoreOutOfDate";
import { Card } from "@/components/mc/ui";
import type { TextV2LeaderboardRow, TextV2ResultDetail } from "@/components/mc/TextV2Results";
import type { TextV2Severity } from "@/lib/text-v2-results";

type Level = TextV2Severity | "unresolved";
type Sort = "descending" | "ascending" | null;

const LEVELS: Level[] = ["none", "mild", "moderate", "severe", "unresolved"];
const NAME: Record<Level, string> = { none: "None", mild: "Mild", moderate: "Moderate", severe: "Severe", unresolved: "Unresolved" };
const FILL: Record<Level, string> = { none: "bg-(--mc-sev-none)", mild: "bg-(--mc-sev-mild)", moderate: "bg-(--mc-sev-moderate)", severe: "bg-(--mc-sev-severe)", unresolved: "bg-mc-dot-none" };
const TINT: Record<Level, string> = { none: "bg-(--mc-sev-none)/15", mild: "bg-(--mc-sev-mild)/20", moderate: "bg-(--mc-sev-moderate)/15", severe: "bg-(--mc-sev-severe)/15", unresolved: "bg-mc-surface-2" };
const count = (row: TextV2LeaderboardRow, level: Level): number => row[level];
const behindReview = (n: number): string => n === 1 ? "1 score behind a finished review" : `${n} scores behind finished reviews`;
const caseName = (id: string): string => id.replace(/^Case(\d{3,})$/, "Case-$1");

export function sortByMeanF1(rows: TextV2LeaderboardRow[], sort: Sort): TextV2LeaderboardRow[] {
  if (!sort) return rows;
  const sign = sort === "descending" ? -1 : 1;
  // Rows without a mean F1 stay last; ties keep project order (Array.prototype.sort is stable).
  return [...rows].sort((a, b) => {
    if (a.meanF1 === null || b.meanF1 === null) return Number(a.meanF1 === null) - Number(b.meanF1 === null);
    return sign * (a.meanF1 - b.meanF1);
  });
}

function SortIcon({ sort }: { sort: Sort }): ReactNode {
  return <svg aria-hidden="true" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 12 12">
    <path className={sort === "ascending" ? "opacity-100" : "opacity-35"} d="M3 5l3-3 3 3" />
    <path className={sort === "descending" ? "opacity-100" : "opacity-35"} d="M3 7l3 3 3-3" />
  </svg>;
}

function F1Cell({ row }: { row: TextV2LeaderboardRow }): ReactNode {
  if (row.meanF1 === null) return <div className="flex flex-col gap-1"><span className="text-mc-muted">-</span>{row.previousPipeline ? <span className="text-xs text-mc-muted">Scored by an earlier grading version</span> : row.scored > 0 && <span className="text-xs text-mc-muted">0 of {row.scored} final</span>}</div>;
  const current = row.scored - row.incomplete;
  return <div className="flex min-w-36 flex-col gap-1">
    <div className="flex items-center gap-2.5">
      <span className="w-11 font-semibold tabular-nums">{row.meanF1.toFixed(3)}</span>
      <span aria-hidden="true" className="h-1.5 flex-1 overflow-hidden rounded-full bg-mc-surface-2"><span className="block h-full rounded-full bg-mc-score transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${Math.max(0, Math.min(1, row.meanF1)) * 100}%` }} /></span>
    </div>
    {!row.previousPipeline && <span className="text-xs text-mc-muted">{current} of {row.scored} final</span>}
  </div>;
}

function SeverityBar({ row }: { row: TextV2LeaderboardRow }): ReactNode {
  if (!row.scored) return <span className="text-xs text-mc-muted">No scores yet</span>;
  const present = LEVELS.filter(level => count(row, level) > 0);
  return <div className="flex min-w-52 flex-col gap-1.5">
    <div aria-hidden="true" className="flex h-2.5 gap-0.5 overflow-hidden rounded-full bg-mc-surface-2">{present.map(level => <span className={FILL[level]} key={level} style={{ flex: count(row, level) }} />)}</div>
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-mc-muted">{present.map(level => <span className="inline-flex items-center gap-1" key={level}><span aria-hidden="true" className={`h-2 w-2 rounded-full ${FILL[level]}`} />{NAME[level]} {count(row, level)}</span>)}</div>
  </div>;
}

function Severity({ level }: { level: Level }): ReactNode {
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-px text-xs font-semibold text-mc-ink ${TINT[level]}`}><span aria-hidden="true" className={`h-[7px] w-[7px] rounded-full ${FILL[level]}`} />{NAME[level]}</span>;
}

function GridCell({ detail }: { detail: TextV2ResultDetail | undefined }): ReactNode {
  if (!detail) return <span className="text-xs text-mc-muted">-</span>;
  const level: Level = detail.worstError ?? "unresolved";
  const upper = detail.worstErrorUpperBound;
  return <Link aria-label={`${caseName(detail.caseId)}, trial ${detail.trial}: ${detail.status}. ${detail.action}`} className="-mx-2 -my-1.5 flex flex-col items-start gap-1 rounded-md px-2 py-1.5 transition-colors hover:bg-mc-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent" href={detail.href}>
    {detail.scored ? <>
      <Severity level={level} />
      {upper && detail.worstError !== null && upper !== detail.worstError && <span className="text-xs text-mc-muted">Provisional</span>}
      {detail.f1 !== null && <span className="text-xs tabular-nums text-mc-muted">F1 {detail.f1.toFixed(3)}</span>}
      {detail.pending && <span className="text-xs text-mc-muted">Severe review pending</span>}
    </> : <>
      <span className="text-xs text-mc-muted">{detail.status}</span>
      <span className="text-xs text-mc-accent underline decoration-mc-accent/40 underline-offset-4">{detail.action}</span>
    </>}
  </Link>;
}

const ALL = "all";
const promptKey = (row: TextV2LeaderboardRow): string => row.promptSha256 ?? "";

export default function TextV2LeaderboardTable({ rows, details, labels, baseLabels = labels, empty, project = "" }: { rows: TextV2LeaderboardRow[]; details: TextV2ResultDetail[]; labels: Record<string, string>; baseLabels?: Record<string, string>; empty?: ReactNode; project?: string }) {
  const [sort, setSort] = useState<Sort>(null);
  const [prompt, setPrompt] = useState(ALL);
  const prompts = [...new Map(rows.map(row => [promptKey(row), row.prompt ?? "No prompt"])).entries()];
  const shown = prompt === ALL ? rows : rows.filter(row => promptKey(row) === prompt);
  const name = prompt === ALL ? labels : baseLabels;
  const ordered = sortByMeanF1(shown, sort);
  const next: Record<string, Sort> = { null: "descending", descending: "ascending", ascending: null };
  const lineKey = (detail: TextV2ResultDetail): string => JSON.stringify([detail.caseId, detail.itemId, detail.trial]);
  const lines = [...new Map(details.map(detail => [lineKey(detail), detail])).values()];
  const cells = new Map(details.map(detail => [`${detail.model} ${lineKey(detail)}`, detail]));
  const trials = Math.max(1, ...details.map(detail => detail.trial));
  const th = "px-3 py-2 text-left text-xs font-semibold text-mc-muted";
  return <>
    <Card className="mb-4 overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pb-2 pt-4">
        <div><h2 className="m-0 text-[15px] font-semibold">Models</h2><p className="mb-0 mt-1 text-[13.5px] text-mc-muted">Each response and trial has equal weight. Models are listed in project order unless sorted by mean F1.</p></div>
        {prompts.length > 1 && <div className="flex items-center gap-2"><label className="text-[13px] font-medium" htmlFor="leaderboard-prompt">Prompt</label><Dropdown aria-label="Prompt" className="w-48 max-w-full rounded-md border border-mc-line bg-mc-surface-2 px-2 py-1 text-[13.5px] text-mc-ink" id="leaderboard-prompt" value={prompt} onChange={event => setPrompt(event.target.value)}><option value={ALL}>All prompts</option>{prompts.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</Dropdown></div>}
      </div>
      {empty}
      <div className="overflow-x-auto"><table className="w-full border-collapse text-[13px]">
        <caption className="sr-only">Scoring results by model</caption>
        <thead><tr>
          <th className={th} scope="col">Model</th><th className={th} scope="col">Scored</th>
          <th aria-sort={sort ?? "none"} className={th} scope="col"><button className="inline-flex items-center gap-1 rounded-sm hover:text-mc-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent" onClick={() => setSort(next[String(sort)])} type="button">Mean F1<SortIcon sort={sort} /></button></th>
          <th className={th} scope="col">Worst error per response</th>
        </tr></thead>
        <tbody>{ordered.map(row => <tr className="border-t border-mc-line align-top" key={row.model}>
          <th className="px-3 py-3 text-left font-semibold" scope="row">{name[row.model]}</th>
          <td className="whitespace-nowrap px-3 py-3 tabular-nums">{row.scored} of {row.expected}{row.scored > 0 && <span className="block text-xs text-mc-muted">{row.clinicianReviewed} of {row.scored} reviewed</span>}{row.scoresBehindReview > 0 && <div className="mt-2"><ScoreOutOfDate project={project} note={behindReview(row.scoresBehindReview)} /></div>}</td>
          <td className="px-3 py-3"><F1Cell row={row} /></td>
          <td className="px-3 py-3"><SeverityBar row={row} /></td>
        </tr>)}</tbody>
      </table></div>
      <p className="m-0 border-t border-mc-line px-5 py-3 text-xs text-mc-muted">Mean F1 averages final scores only. A score is final once every item is rated and no severe review is waiting. Worst error counts use each score&apos;s current reading; a provisional score&apos;s worst error may rise once its judgment is settled. Scored counts current scores out of every expected response; missing, failed, and unscored responses show in By case. No rank is assigned.</p>
    </Card>
    {lines.length > 0 && <Card className="mb-4 overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-5 pb-2 pt-4"><h2 className="m-0 text-[15px] font-semibold">By case</h2><p className="m-0 text-xs text-mc-muted">Select a cell to open its score or next step</p></div>
      <div className="overflow-x-auto"><table className="w-full border-collapse text-[13px]">
        <caption className="sr-only">Worst error and F1 for each case by model</caption>
        <thead><tr><th className={th} scope="col">Case</th>{ordered.map(row => <th className={th} key={row.model} scope="col">{name[row.model]}</th>)}</tr></thead>
        <tbody>{lines.map(line => <tr className="border-t border-mc-line align-top" key={`${line.caseId}:${line.itemId}:${line.trial}`}>
          <th className="px-3 py-2.5 text-left font-semibold" scope="row">{caseName(line.caseId)}{line.itemId !== line.caseId && <span className="block text-xs font-normal text-mc-muted">{line.itemId}</span>}{trials > 1 && <span className="block text-xs font-normal text-mc-muted">trial {line.trial}</span>}</th>
          {ordered.map(row => <td className="px-3 py-2.5" key={row.model}><GridCell detail={cells.get(`${row.model} ${lineKey(line)}`)} /></td>)}
        </tr>)}</tbody>
      </table></div>
    </Card>}
  </>;
}

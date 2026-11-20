import { expectedTrial, projectTrials, trialNumbers } from "@/lib/caseset/trials";
import type { WorstHarm } from "@/lib/answer-score";
import type { AttentionTarget, Benchmark, ResponseStatus } from "@/lib/caseset/metrics";

export interface LeaderboardRow {
  model: string;
  rank: number | null;
  status: "ranked" | "partial" | "unverified" | "not scored";
  f1: number | null;
  recall: number | null;
  precision: number | null;
  worstHarm: WorstHarm | null;
  // Each scored response appears once, under its stored worst harm.
  harmCounts: Record<WorstHarm, number>;
  unknownHarmCount: number;
  scored: number;
  expected: number;
  scoredCases: number;
  totalCases: number;
  missing: number;
  failed: number;
  unscored: number;
  draft: boolean;
  provisional: boolean;
  unverified: boolean;
  draftCount: number;
  provisionalCount: number;
  unverifiedCount: number;
  reviewed: number;
  mixedRubrics: boolean;
  mixedJudges: boolean;
  target: AttentionTarget | null;
}

const HARM_ORDER: WorstHarm[] = ["none", "uncertain", "mild", "moderate", "severe"];
const compareText = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;
const metric = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
const usable = ({ row }: ResponseStatus): boolean => row.response !== null && row.responseError === null && row.judge === "pass" && (row.scoreCheck === "current" || row.scoreCheck === "unverified") && row.scored !== null && [row.scored.f1, row.scored.recall, row.scored.precision].every(metric);
const provisional = (response: ResponseStatus): boolean => response.row.scored !== null && (
  response.row.scored.provisional || response.row.scored.offRubricProvisional ||
  Object.values(response.row.scored.decisions).some((d) => d.state === "provisional") ||
  response.limits.some((limit) => limit !== "score inputs not recorded")
);

// A development ranking of stored response-level means. Review and harm stay separate.
export function buildLeaderboard(bench: Pick<Benchmark, "models" | "cases" | "trials">): LeaderboardRow[] {
  const trials = projectTrials(bench.trials);
  const rows = [...new Set(bench.models)].map((model): LeaderboardRow => {
    const allResponses = bench.cases.flatMap((c) => c.responses.filter((r) => r.row.model === model));
    const responses = bench.cases.flatMap((c) => c.responses.filter((r) => r.row.model === model && c.items.includes(r.row.itemId) && expectedTrial(r.row.trial, trials)));
    const identities = new Set(responses.map((r) => `${r.caseId}\t${r.row.itemId}\t${r.row.trial}`));
    const unexpected = allResponses.length !== responses.length || identities.size !== responses.length;
    const absent = bench.cases.flatMap((c) => c.items.flatMap((itemId) => trialNumbers(trials)
      .filter((trial) => !identities.has(`${c.caseId}\t${itemId}\t${trial}`))
      .map((trial) => ({ caseId: c.caseId, itemId, model, trial }))));
    const scored = responses.filter(usable).sort((a, b) => compareText(a.caseId, b.caseId) || compareText(a.row.itemId, b.row.itemId) || a.row.trial - b.row.trial);
    const expected = bench.cases.reduce((n, c) => n + c.items.length * trials, 0);
    const mean = (key: "f1" | "recall" | "precision"): number | null => scored.length ? scored.reduce((sum, r) => sum + r.row.scored![key], 0) / scored.length : null;
    const draftCount = scored.filter((r) => !r.scoreReviewed).length;
    const provisionalCount = scored.filter(provisional).length;
    const unverifiedCount = scored.filter((r) => r.row.scoreCheck === "unverified").length;
    const harmCounts: Record<WorstHarm, number> = { none: 0, uncertain: 0, mild: 0, moderate: 0, severe: 0 };
    let unknownHarmCount = 0;
    for (const r of scored) {
      const harm = r.row.scored!.worstHarm;
      if (HARM_ORDER.includes(harm as WorstHarm)) harmCounts[harm as WorstHarm] += 1;
      else unknownHarmCount += 1;
    }
    const first = scored[0] ?? [...responses].sort((a, b) => compareText(a.caseId, b.caseId) || compareText(a.row.itemId, b.row.itemId) || a.row.trial - b.row.trial)[0];
    const firstMissing = [...absent].sort((a, b) => compareText(a.caseId, b.caseId) || compareText(a.itemId, b.itemId) || a.trial - b.trial)[0];
    return {
      model, rank: null,
      status: !scored.length ? "not scored" : unexpected || scored.length !== expected ? "partial" : unverifiedCount ? "unverified" : "ranked",
      f1: mean("f1"), recall: mean("recall"), precision: mean("precision"),
      worstHarm: [...HARM_ORDER].reverse().find((harm) => harmCounts[harm] > 0) ?? null,
      harmCounts, unknownHarmCount,
      scored: scored.length, expected, scoredCases: new Set(scored.map((r) => r.caseId)).size, totalCases: bench.cases.length,
      missing: absent.length + responses.filter((r) => r.row.response === null).length,
      failed: responses.filter((r) => r.row.responseError !== null || r.row.judge === "failed").length,
      unscored: Math.max(0, expected - scored.length),
      draft: draftCount > 0, provisional: provisionalCount > 0, unverified: unverifiedCount > 0,
      draftCount, provisionalCount, unverifiedCount,
      reviewed: scored.filter((r) => r.scoreReviewed && r.row.scoreCheck === "current" && !provisional(r)).length,
      mixedRubrics: bench.cases.some((c) => new Set(scored.filter((r) => r.caseId === c.caseId).map((r) => `${r.row.scored!.rubric}:${r.row.scored!.rubric_sha256 ?? r.row.record?.rubric_sha256 ?? ""}`)).size > 1),
      mixedJudges: new Set(scored.map((r) => r.row.scored!.judgeModel)).size > 1,
      target: first ? { case: first.caseId, item: first.row.itemId, model, trial: first.row.trial } : firstMissing ? { case: firstMissing.caseId, item: firstMissing.itemId, model, trial: firstMissing.trial } : null,
    };
  }).sort((a, b) => a.f1 === null ? b.f1 === null ? compareText(a.model, b.model) : 1 : b.f1 === null ? -1 : b.f1 - a.f1 || compareText(a.model, b.model));

  let position = 0;
  let previous: LeaderboardRow | undefined;
  for (const row of rows) {
    if (row.f1 === null) continue;
    position += 1;
    row.rank = previous?.f1 === row.f1 ? previous.rank : position;
    previous = row;
  }
  return rows;
}

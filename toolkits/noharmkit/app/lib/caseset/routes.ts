import type { Benchmark } from "@/lib/caseset/metrics";
import { noharmHref } from "@/lib/noharm-path";
import { STEP_KEYS, stepForRoute } from "@/lib/caseset/steps";
import type { StepKey } from "@/lib/caseset/steps";
import type { TableVersion } from "@/lib/caseset/types";

export type PageKey = StepKey | "framework" | "review";
export interface StepParams { caseId: string; version: string | null; itemId: string; model: string | null; trial: number }

const ORDER = ["case", "version", "item", "model", "trial"] as const;

export function navigationParams(search: Pick<URLSearchParams, "get">): Record<string, string | null> {
  return Object.fromEntries(ORDER.map((key) => [key, search.get(key)]));
}

export function stepHref(page: PageKey, params: Record<string, string | number | null | undefined> = {}): string {
  if (page === "leaderboard") return noharmHref("/leaderboard");
  const query = new URLSearchParams();
  for (const key of ORDER) {
    const value = params[key];
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const q = query.toString();
  return noharmHref(`/${page === "cases" ? "dataset" : page}${q ? `?${q}` : ""}`);
}

export function datasetRedirect(query: Record<string, string | string[] | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, values] of Object.entries(query)) {
    for (const value of Array.isArray(values) ? values : values === undefined ? [] : [values]) search.append(key, value);
  }
  const encoded = search.toString();
  return noharmHref(`/dataset${encoded ? `?${encoded}` : ""}`);
}

const one = (value: string | string[] | undefined): string | undefined => (typeof value === "string" ? value : undefined);

function authoringVersion(tables: TableVersion[]): string | undefined {
  const passing = tables.filter((table) => table.status === "pass" && (table.record || table.textV2));
  const latest = passing.filter((table) => table.kind === "run")
    .sort((a, b) => Number(b.version.slice(3)) - Number(a.version.slice(3)))[0];
  const reviewed = passing.filter((table) => table.kind === "reviewed" && (!latest
    || (table.basedOn?.version === latest.version && table.basedOn.sha256 === latest.sha256)))
    .sort((a, b) => (b.savedAt ?? "").localeCompare(a.savedAt ?? ""))[0];
  return reviewed?.version ?? latest?.version;
}

export function resolveStepParams(bench: Benchmark, query: Record<string, string | string[] | undefined>, step?: StepKey): StepParams | null {
  if (!bench.cases.length) return null;
  const c = bench.cases.find((x) => x.caseId === one(query.case)) ?? bench.cases[0];
  const labels = c.page.tables.map((t) => t.version);
  const asked = one(query.version);
  const passing = c.page.tables.find((t) => t.status === "pass" && (t.record || t.textV2))?.version;
  const authoring = step === "rubrics" ? authoringVersion(c.page.tables) : undefined;
  const version = asked && labels.includes(asked) ? asked : authoring ?? c.rubric.versions[0] ?? passing ?? labels[0] ?? null;
  const items = c.items.length ? c.items : [c.caseId];
  const itemId = items.find((i) => i === one(query.item)) ?? (items.includes(c.caseId) ? c.caseId : items[0]);
  const models = [...new Set([...c.responses.map((r) => r.row.model), ...bench.models])].sort();
  const model = models.find((m) => m === one(query.model)) ?? models[0] ?? null;
  const trial = Number(one(query.trial));
  // A missing answer is still an identity the user can open.
  const exists = c.responses.some((r) => r.row.model === model && r.row.itemId === itemId && r.row.trial === trial)
    || c.missing.some((m) => m.model === model && m.itemId === itemId && m.trial === trial);
  return { caseId: c.caseId, version, itemId, model, trial: exists ? trial : 1 };
}

export function keyTarget(key: string, pathname: string, params: Record<string, string | null>): string | null {
  const at = (step: StepKey): string => stepHref(step, params);
  const current = STEP_KEYS.findIndex((k) => k === stepForRoute(pathname.slice(1)));
  if (pathname === "/review") return null;
  if (key === "d" || key === "D") return noharmHref("/dashboard");
  if (/^[1-6]$/.test(key)) return at(STEP_KEYS[Number(key) - 1]);
  if (key === "ArrowRight") return current < 0 ? at("cases") : current < STEP_KEYS.length - 1 ? at(STEP_KEYS[current + 1]) : null;
  if (key === "ArrowLeft") return current < 0 ? null : current === 0 ? noharmHref("/welcome") : at(STEP_KEYS[current - 1]);
  return null;
}

// Base case ids are hyphen-free; a perturbation variant is <base>-<n> (CLAUDE.md, ID rules).
export function runsRedirect(segments: string[], query: Record<string, string | string[] | undefined>): string {
  const [caseset, id, kind, a, b] = segments;
  if (!caseset) return noharmHref("/dashboard");
  if (kind === "table" && id && a) return stepHref("review", { case: id, version: a });
  if (kind === "response" && id && a) return stepHref("autograding", { case: id.split("-")[0], item: id, model: a, trial: b });
  return stepHref("cases", { case: one(query.case) });
}

export function relativeTime(iso: string | null, now: Date): string {
  if (!iso) return "at an unknown time";
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  const days = Math.floor(seconds / 86400);
  return `${days} ${days === 1 ? "day" : "days"} ago`;
}

export type Metric = { category: string; name: string; value: number; n: number; ci: number | null };
export type Case = { id: string; trial: number; prompt: string; expected: unknown; response: unknown; error: string | null; metadata: Record<string, unknown>; outcome: string; metrics: Metric[] };
export type IterationRoute = { stage: "data-intake" | "rubric-design" | "study-design"; label: string; purpose: string };
export type IterationReview = {
  schema_version: "arisekit.iteration-review.v1";
  run_id: string;
  counts: Record<"passed" | "failed" | "scored" | "unscored" | "error" | "missing", number>;
  opening: string;
  notable_cases: { id: string; trial: number; outcome: string; error: string | null; metrics: { name: string; value: unknown }[] }[];
  revision_routes: IterationRoute[];
};
export type Run = { id: string; kind: string; cases: Case[]; expected_count: number; missing_count: number; manifest: Record<string, unknown>; bundle: {
  model: string; run_manifest_digest: string; metrics: Metric[];
  summary: { completed: number; errored: number; skipped: number; cost_total: number; calls_total: number; cost_unknown: boolean; budget_exhausted: boolean; call_budget_exhausted: boolean; cost_bound_exceeded: boolean };
}; iteration_review?: IterationReview };
export type Job = { id: string; operation: string; status: string; result?: unknown; error?: string };
export type Workspace = {
  items?: Record<string, unknown>[];
  name: string; slug: string; readiness: string; build_spec_sha256: string;
  plan: unknown; artifacts: { role: string; sha256: string; text: string }[];
  runs: Run[]; routes: { model: string; provider: string; trials: number }[];
  runner: { max_tokens: number | null; max_cost: number | null; max_calls: number | null };
  operations: Job[];
  smoke_test: { model: string; limit: number; trials: number; status: string };
  worker: { kind: string; azure_missing: string[] };
};

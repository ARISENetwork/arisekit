import type { IterationReview, IterationRoute, Run } from "./workspaceTypes";

const routes: IterationRoute[] = [
  { stage: "data-intake", label: "Revise cases or references", purpose: "Change source-case coverage, case wording, field mapping, or reference answers." },
  { stage: "rubric-design", label: "Revise the rubric", purpose: "Change scoring criteria, anchors, weights, or the scorer binding." },
  { stage: "study-design", label: "Revise the review plan", purpose: "Change expert review, disagreement handling, or the planned analysis." },
];

export function reviewForRun(run: Run): IterationReview {
  if (run.iteration_review?.schema_version === "arisekit.iteration-review.v1") return run.iteration_review;
  const counts = { passed: 0, failed: 0, scored: 0, unscored: 0, error: 0, missing: 0 };
  for (const row of run.cases) {
    if (row.outcome in counts) counts[row.outcome as keyof typeof counts] += 1;
  }
  const opening = counts.error || counts.missing
    ? "Start with incomplete or errored trials before changing the benchmark definition."
    : counts.failed
      ? "Start with the failed cases and compare each response with its reference and scoring rule."
      : "The run has no failed, missing, or errored cases. Review coverage before deciding whether a revision is useful.";
  return {
    schema_version: "arisekit.iteration-review.v1",
    run_id: run.id,
    counts,
    opening,
    notable_cases: run.cases.filter(row => ["error", "missing", "failed"].includes(row.outcome)).map(row => ({
      id: row.id, trial: row.trial, outcome: row.outcome, error: row.error,
      metrics: row.metrics.map(metric => ({ name: metric.name, value: metric.value })),
    })),
    revision_routes: routes,
  };
}

export function iterationPrompt(
  run: Run,
  route: IterationRoute,
  selectedCases: string[],
  observation: string,
): string {
  const caseText = selectedCases.length ? selectedCases.join(", ") : "the run as a whole";
  const note = observation.trim();
  const artifact = route.stage === "data-intake" ? "data-profile.md"
    : route.stage === "rubric-design" ? "rubric.md" : "study-plan.md";
  return [
    `I reviewed run ${run.bundle.run_manifest_digest.slice(0, 12)} and want to revisit ${caseText}.`,
    note ? `My observation: ${note}` : "Help me inspect what the retained outcomes imply before I decide what to change.",
    `${route.purpose} Ask me one focused question at a time. Use the current draft and upstream artifacts, and do not assume a revision is warranted. When we agree on a change, update ${artifact}.`,
  ].join(" ");
}

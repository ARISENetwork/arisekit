import { rubricReviewProgress } from "@/lib/caseset/metrics";
import type { CaseStatus } from "@/lib/caseset/metrics";

export default function RubricReviewProgress({ cases, compact = false }: { cases: CaseStatus[]; compact?: boolean }) {
  const progress = rubricReviewProgress(cases);
  if (compact) {
    return <span className="font-mc-mono text-xs text-mc-muted" title={progress.usedTotal
      ? `${progress.usedReviewed} of ${progress.usedTotal} cases use reviewed rubrics in results`
      : "No autograding yet"}>{progress.savedReviewed} of {progress.savedTotal} reviewed</span>;
  }
  return (
    <div className="flex flex-col gap-1 text-xs text-mc-muted">
      <span>Saved rubric review: {progress.savedReviewed} of {progress.savedTotal} cases</span>
      <span>{progress.usedTotal
        ? `Rubrics used in results: ${progress.usedReviewed} of ${progress.usedTotal} cases reviewed`
        : "Results: no autograding yet"}</span>
    </div>
  );
}

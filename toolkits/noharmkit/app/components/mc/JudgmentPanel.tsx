"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";

import JudgmentReview, { type ReviewSetup } from "@/components/mc/JudgmentReview";
import TextV2JudgmentList, { type JudgmentListData } from "@/components/mc/TextV2JudgmentList";
import { RescoreNotice, rescore, type Rescore } from "@/components/mc/rescore";
import styles from "./JudgmentReview.module.css";

export interface ReviewedReading { data: JudgmentListData; reviewer: string; reviewedAt: string; rubricReviewed: boolean }

// The Judgment panel: the judge's reading, or the current finished review's, with clinician review on pipeline-v2.
export default function JudgmentPanel({ judge, reviewed, review }: { judge: JudgmentListData; reviewed: ReviewedReading | null; review: ReviewSetup | null }): ReactNode {
  const router = useRouter();
  const [reviewing, setReviewing] = useState(false);
  const [showJudge, setShowJudge] = useState(false);
  const [status, setStatus] = useState<Rescore | null>(null);

  const finished = async (): Promise<void> => {
    setReviewing(false);
    setShowJudge(false);
    router.refresh();
    if (!review) return;
    setStatus({ phase: "running" });
    setStatus(await rescore(review.project));
    router.refresh();
  };

  if (reviewing && review) return <JudgmentReview setup={review} onClose={() => setReviewing(false)} onFinished={() => void finished()} />;
  const showReviewed = reviewed !== null && !showJudge;
  return <div className={styles.panel}>
    {(reviewed || review) && <div className={styles.bar}>
      <p>{reviewed ? <>{showReviewed ? "Reviewed" : "Judge's reading. Reviewed"} by <strong>{reviewed.reviewer}</strong>, {reviewed.reviewedAt.slice(0, 10)}.{!reviewed.rubricReviewed && " Rubric not yet reviewed."}</> : "Check each rubric item the judge read, then finish to update the score."}</p>
      <span className={styles.tools}>
        {reviewed && <button className={styles.button} type="button" onClick={() => setShowJudge((value) => !value)}>{showJudge ? "Show reviewed reading" : "Show judge's reading"}</button>}
        {review && <button className={styles.button} type="button" disabled={status?.phase === "running"} onClick={() => { setStatus(null); setReviewing(true); }}>Review judgment</button>}
      </span>
    </div>}
    {status && <RescoreNotice state={status} />}
    <TextV2JudgmentList data={showReviewed ? reviewed.data : judge} />
  </div>;
}

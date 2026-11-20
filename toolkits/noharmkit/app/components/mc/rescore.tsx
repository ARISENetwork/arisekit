import type { ReactNode } from "react";

import { consumeApiPipelineStream, type ApiRunEvent } from "@/components/mc/ApiExecution";
import styles from "./JudgmentReview.module.css";

export type Rescore = { phase: "running" } | { phase: "done"; gaps: string[] } | { phase: "failed"; error: string };

export async function rescore(project: string): Promise<Rescore> {
  let response: Response;
  try {
    response = await fetch("/api/pipeline/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, action: { stage: "score", allowPartial: true } }) });
  } catch {
    return { phase: "failed", error: "No connection." };
  }
  if (!response.ok || !response.body) {
    const text = await response.text();
    try { return { phase: "failed", error: (JSON.parse(text) as { error?: string }).error ?? text }; } catch { return { phase: "failed", error: text || `HTTP ${response.status}` }; }
  }
  let result: ApiRunEvent | null = null;
  try {
    await consumeApiPipelineStream(response.body, (event) => { if (event.type === "result") result = event; });
  } catch (error) {
    return { phase: "failed", error: (error as Error).message };
  }
  const final = result as ApiRunEvent | null;
  if (!final) return { phase: "failed", error: "The scoring run ended before reporting a result." };
  if (final.status !== "completed") return { phase: "failed", error: final.error ?? final.message ?? "Scoring did not complete." };
  return { phase: "done", gaps: final.gaps ?? [] };
}

export function RescoreNotice({ state }: { state: Rescore }): ReactNode {
  if (state.phase === "running") return <p className={styles.notice} role="status">Review finished. Updating scores locally, with no model calls.</p>;
  if (state.phase === "failed") return <div className={styles.notice} data-tone="bad" role="alert"><p>Review finished and saved. Scores did not update.</p><p>{state.error}</p><p>Run Compute Scores on the Scores step to try again.</p></div>;
  if (!state.gaps.length) return <p className={styles.notice} role="status">Review finished. Scores updated.</p>;
  return <div className={styles.notice} data-tone="bad" role="alert">
    <p>Scored, but {state.gaps.length} {state.gaps.length === 1 ? "response" : "responses"} could not be scored:</p>
    <ul>{state.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>
  </div>;
}

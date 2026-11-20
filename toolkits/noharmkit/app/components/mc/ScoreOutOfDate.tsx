"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";

import { RescoreNotice, rescore, type Rescore } from "@/components/mc/rescore";

// Shown when a finished clinician review is newer than the stored score. The result stays after the refresh, so a score that is still behind says why.
export default function ScoreOutOfDate({ project, initial = null, note }: { project: string; initial?: Rescore | null; note?: string }): ReactNode {
  const router = useRouter();
  const [state, setState] = useState<Rescore | null>(initial);
  const run = async (): Promise<void> => {
    setState({ phase: "running" });
    setState(await rescore(project));
    router.refresh();
  };
  const running = state?.phase === "running";
  return <div className="flex flex-col items-start gap-2">
    <p className="m-0 text-sm text-mc-muted" role="status">{note ?? "Scores out of date."}</p>
    <button className="rounded-md border border-mc-line bg-mc-surface-2 px-3 py-1 text-[13.5px] text-mc-ink hover:bg-mc-line disabled:opacity-60" type="button" disabled={running} onClick={() => void run()}>{running ? "Computing…" : "Compute Scores"}</button>
    {state && !running && <RescoreNotice state={state} />}
  </div>;
}

"use client";

import { useEffect, useRef, useState, type ReactElement } from "react";
import type { RecoveryPlan, RecoveryTicket } from "@/lib/pipeline-recovery";
import RunPromptDetails from "./RunPromptDetails";
import type { RunPromptView } from "@/lib/response-prompt-picker";
import runStyles from "./ApiExecution.module.css";
import styles from "./ApiRunRecovery.module.css";

export default function ApiRunRecovery({ project, jobId, prompt, busy, onResume, onRefresh }: { project: string; jobId: string; prompt: RunPromptView | null; busy: boolean; onResume: (ticket: RecoveryTicket) => Promise<void>; onRefresh: () => Promise<void> }): ReactElement {
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [plan, setPlan] = useState<RecoveryPlan | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => { setOpen(false); setPlan(null); setChecking(false); setError(null); return () => request.current?.abort(); }, [project, jobId]);
  const inspect = async (): Promise<void> => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setOpen(true); setChecking(true); setError(null); setPlan(null);
    try {
      const response = await fetch(`/api/pipeline/recovery?project=${encodeURIComponent(project)}`, { cache: "no-store", signal: controller.signal });
      const result = await response.json() as { plan?: RecoveryPlan; error?: string };
      if (!response.ok || !result.plan) throw new Error(result.error ?? `Recovery inspection returned HTTP ${response.status}.`);
      if (result.plan.jobId !== jobId) throw new Error("The saved run changed. Check saved status before reviewing it again.");
      setPlan(result.plan); setName(result.plan.suggestedName ?? "");
    } catch (caught) { if (!controller.signal.aborted) setError((caught as Error).message); }
    finally { if (!controller.signal.aborted) setChecking(false); }
  };
  const newRun = async (): Promise<void> => {
    if (!plan?.token) return;
    setChecking(true); setError(null);
    try {
      const response = await fetch("/api/pipeline/recovery", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, name, ticket: { jobId, token: plan.token } }) });
      const result = await response.json() as { href?: string; error?: string };
      if (!response.ok) throw new Error(result.error ?? `New run returned HTTP ${response.status}.`);
      window.location.assign(result.href ?? "/noharm/api-setup");
    } catch (caught) { setError((caught as Error).message); setChecking(false); }
  };
  return <div className={runStyles.recovery}>
    <button className={runStyles.button} type="button" disabled={busy || checking} aria-expanded={open} onClick={() => { if (open) setOpen(false); else void inspect(); }}>{open ? "Hide saved work" : "Review saved work"}</button>
    <div className={styles.disclosure} data-open={open} inert={!open || undefined} aria-hidden={!open || undefined}>
      <div className={styles.inner}><div className={styles.inspection} aria-busy={checking}>
        <h2>Saved work</h2>
        {checking && <p role="status">Checking the run and saved outputs. No model calls are being made.</p>}
        {error && <p className={runStyles.error} role="alert">{error}</p>}
        {plan && <>
          <p>{plan.reason}</p>
          {plan.status === "ready" && <>
            {prompt && <RunPromptDetails prompt={prompt} />}
            <p>Validated call receipts: {plan.reusableCalls}.{plan.restoredFiles > 0 && ` Retained files available to restore: ${plan.restoredFiles}.`}</p>
            <p>{plan.pending ? "Only remaining calls use API credits. Verified completed outputs are reused." : "This stage can finish without new model calls."}</p>
            {prompt?.state !== "blocked" && <button className={runStyles.button} type="button" disabled={busy || checking || prompt?.state === "loading"} onClick={() => { setPlan(null); void onResume({ jobId, token: plan.token! }); }}>{plan.pending ? "Resume remaining work" : "Finish from saved work"}</button>}
          </>}
          {plan.status === "new-run" && <>
            <p>A new run is a separate named project. Current source inputs and prior-stage artifacts are copied; the original run and its outputs remain unchanged. Creating it makes no model calls.</p>
            <label className={runStyles.runName}>New run name<input value={name} maxLength={64} pattern="[a-z0-9][a-z0-9-]*" onChange={event => setName(event.target.value)} disabled={busy || checking} /></label>
            <button className={runStyles.button} type="button" disabled={busy || checking || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(name)} onClick={() => void newRun()}>Start a new run</button>
          </>}
          {(plan.status === "running" || plan.status === "completed") && <button className={runStyles.button} type="button" disabled={checking} onClick={() => void onRefresh()}>Check saved status</button>}
        </>}
      </div></div>
    </div>
  </div>;
}

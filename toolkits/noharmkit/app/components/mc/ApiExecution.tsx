"use client";

import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useReducer, useRef, useState, type ComponentProps, type ReactElement, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "@/components/MotionLink";
import PromptBox from "./PromptBox";
import ApiRunRecovery from "./ApiRunRecovery";
import { useApiReadiness } from "./ApiReadiness";
import type { ApiExecutionReadiness } from "@/lib/api-execution-readiness";
import { apiExecutionReducer, executionActive, executionMessage, executionRun, executionStatus, INITIAL_EXECUTION_STATE, type ApiRunEvent, type RunStatus, type StoredRun } from "@/lib/api-execution-state";
import type { RecoveryTicket } from "@/lib/pipeline-recovery";
import type { ApiPipelineAction } from "@/lib/api-pipeline-action";
import type { ApiPipelineConfig } from "@/lib/api-pipeline-config";
import { initialModelTeams, type ApiModelStage } from "@/lib/api-model-teams";
import { REASONING_LABELS, type ReasoningEffort } from "@/lib/api-model-reasoning";
import { localPath, noharmHref } from "@/lib/noharm-path";
import RunPromptDetails from "./RunPromptDetails";
import { runPromptView, type RunPromptView } from "@/lib/response-prompt-picker";
import styles from "./ApiExecution.module.css";

export type { ApiRunEvent } from "@/lib/api-execution-state";
interface ExecutionContext { project: string; mode: "api" | "local"; configured: boolean; run: (action: ApiPipelineAction) => Promise<void>; active: boolean; status: RunStatus | null; error: string | null; readiness: ApiExecutionReadiness | null; readinessError: string | null; openSetup: () => void; panel: ReactNode }
const Context = createContext<ExecutionContext | null>(null);
export const useApiExecution = (): ExecutionContext | null => useContext(Context);
// Loaded on first use: the popup carries the model catalog editor.
const ModelSetupPopup = lazy(() => import("./ModelSetupPopup"));

// Opens model setup over the current page; the link still works where no project run context exists.
// The run card, placed by the page shell under the project's notices.
export function ApiRunPanel(): ReactNode {
  return useApiExecution()?.panel ?? null;
}

export function ModelSetupLink(props: Omit<ComponentProps<typeof Link>, "href">): ReactElement {
  const execution = useApiExecution();
  return <Link {...props} href={noharmHref("/api-setup")} onClick={event => { if (!execution) return; event.preventDefault(); execution.openSetup(); }} />;
}

const STAGE_NAMES = { generate: "Rubric generation", responses: "Response collection", judge: "Autograding", score: "Scores" } as const;

function RunModels({ config, stage }: { config: ApiPipelineConfig; stage: ApiPipelineAction["stage"] }): ReactElement {
  const teams = initialModelTeams(config);
  const used: ApiModelStage[] = stage === "generate" ? ["generation", "rating"] : stage === "responses" ? ["responses"] : stage === "judge" ? ["judge"] : [];
  const names = { generation: "Rubric generation", rating: "Harm rating", responses: "Models under test", judge: "Autograding" };
  const model = (id: string, effort?: ReasoningEffort): string => `${id} (${effort ? REASONING_LABELS[effort] : "model default"})`;
  return <>{used.map(key => <p key={key}>{names[key]}: {teams[key].models.map(id => model(id, teams[key].modelReasoning?.[id])).join(", ") || "skipped"}.{key !== "responses" && teams[key].models.length > 1 && teams[key].integrator && ` Integrator: ${model(teams[key].integrator, teams[key].integratorReasoning?.[teams[key].integrator])}.`}</p>)}</>;
}

function elapsed(run: StoredRun, now: number): string {
  const start = run.startedAt ? Date.parse(run.startedAt) : NaN;
  const end = run.finishedAt ? Date.parse(run.finishedAt) : run.status === "running" ? now : NaN;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "not recorded";
  const seconds = Math.floor((end - start) / 1000);
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function ApiRunMetadata({ run, now, prompt }: { run: StoredRun; now: number; prompt?: RunPromptView | null }): ReactElement {
  const scoring = run.action.stage === "score";
  return <><dl className={styles.metadata}><div><dt>Route</dt><dd>{scoring ? "Local / deterministic" : "API / OpenRouter"}</dd></div><div><dt>Stage</dt><dd>{STAGE_NAMES[run.action.stage]}</dd></div><div><dt>Elapsed</dt><dd>{elapsed(run, now)}</dd></div>{!scoring && <div><dt>Workers</dt><dd>{run.workerCount ?? "not recorded"}</dd></div>}</dl>
    {scoring && <p>Deterministic scoring. No model calls or API credits.</p>}
    {run.config && <RunModels config={run.config} stage={run.action.stage} />}
    {run.action.prompt !== undefined && <RunPromptDetails prompt={prompt ?? { state: "loading", id: run.action.prompt }} />}
  </>;
}

export async function consumeApiPipelineStream(stream: ReadableStream<Uint8Array>, receive: (event: ApiRunEvent) => void): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  const line = (value: string): void => { if (value.trim()) receive(JSON.parse(value) as ApiRunEvent); };
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      lines.forEach(line);
      if (done) { line(pending); return; }
    }
  } finally { reader.releaseLock(); }
}

async function responseError(response: Response): Promise<string> {
  const text = await response.text();
  try { const result = JSON.parse(text) as { error?: string }; return result.error ?? text; }
  catch { return text || `Pipeline returned HTTP ${response.status}.`; }
}

function useRunPrompt(project: string, promptId: string | undefined, enabled: boolean): RunPromptView | null {
  const [view, setView] = useState<RunPromptView | null>(null);
  useEffect(() => {
    if (!promptId || !enabled) { setView(null); return; }
    setView({ state: "loading", id: promptId });
    const controller = new AbortController();
    fetch(`/api/prompts?project=${encodeURIComponent(project)}`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(await responseError(response));
        const data = await response.json() as { prompts: { id: string; name: string; text: string; sha256?: string }[]; recorded?: Record<string, string> };
        setView(runPromptView(promptId, data.prompts, data.recorded ?? {}));
      })
      .catch((caught: Error) => { if (!controller.signal.aborted) setView({ state: "blocked", id: promptId, reason: `The saved prompt could not be checked: ${caught.message}` }); });
    return () => controller.abort();
  }, [project, promptId, enabled]);
  return view;
}

export default function ApiExecutionProvider({ project, mode, configured, children }: { project: string; mode: "api" | "local"; configured: boolean; children: ReactNode }): ReactElement {
  const router = useRouter();
  const [state, dispatch] = useReducer(apiExecutionReducer, INITIAL_EXECUTION_STATE);
  const [streaming, setStreaming] = useState(false);
  const [now, setNow] = useState(Date.now);
  const active = executionActive(state);
  const lastRun = executionRun(state);
  const status = executionStatus(state);
  const message = executionMessage(state);
  const runPrompt = useRunPrompt(project, lastRun?.action.prompt, mode === "api" && Boolean(lastRun?.jobId));
  const error = state.error;
  const { readiness, error: readinessError, refresh: refreshReadiness } = useApiReadiness(mode === "api");
  const busy = useRef(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [setupMounted, setSetupMounted] = useState(false);
  const openSetup = useCallback((): void => { setSetupMounted(true); setSetupOpen(true); }, []);
  const request = useRef<AbortController | null>(null);
  const recovery = useRef<AbortController | null>(null);
  const recover = useCallback(async (): Promise<void> => {
    if (busy.current || mode !== "api") return;
    recovery.current?.abort();
    const controller = new AbortController(); recovery.current = controller;
    try {
      const response = await fetch(`/api/pipeline/run?project=${encodeURIComponent(project)}`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(await responseError(response));
      const result = await response.json() as { run: StoredRun | null };
      if (controller.signal.aborted || busy.current) return;
      dispatch({ type: "load", run: result.run });
    } catch (caught) { if (!controller.signal.aborted) dispatch({ type: "problem", error: (caught as Error).message }); }
  }, [mode, project]);
  useEffect(() => {
    void recover();
    return () => { recovery.current?.abort(); request.current?.abort(); };
  }, [recover]);
  useEffect(() => {
    if (!active) return;
    const leave = (event: BeforeUnloadEvent): void => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [active]);
  useEffect(() => {
    if (!active || !lastRun?.startedAt) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, lastRun?.startedAt]);
  const run = useCallback(async (action: ApiPipelineAction, ticket?: RecoveryTicket): Promise<void> => {
    if (busy.current || active || mode !== "api") return;
    if (!configured) { dispatch({ type: "problem", error: "Choose your API models before running the pipeline." }); return; }
    if (!ticket && lastRun?.jobId && lastRun.action.stage === action.stage && (status === "failed" || status === "interrupted")) { dispatch({ type: "problem", error: "Review saved work before rerunning this stage." }); return; }
    busy.current = true; recovery.current?.abort();
    const controller = new AbortController(); request.current = controller;
    dispatch({ type: "start", action }); setStreaming(true);
    let terminal = false;
    let startRequested = false;
    let rejected = false;
    try {
      const checked = await refreshReadiness();
      const availability = checked?.[action.stage === "score" ? "scoring" : "modelCalls"];
      if (!availability) throw new Error("Execution availability could not be checked. Check availability before trying again.");
      if (!ticket && !availability.available) throw new Error(availability.reason);
      startRequested = true;
      const response = await fetch("/api/pipeline/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, action, ...(ticket ? { recovery: ticket } : {}) }), signal: controller.signal });
      if (!response.ok) { rejected = true; throw new Error(await responseError(response)); }
      if (!response.body) throw new Error("Pipeline returned no event stream.");
      await consumeApiPipelineStream(response.body, event => {
        dispatch({ type: "event", event });
        if (event.type === "result") {
          terminal = true;
          const result = event.status ?? (event.error ? "failed" : "interrupted");
          if (result === "completed") router.refresh();
        }
      });
      if (!terminal) throw new Error("The pipeline connection ended before completion was confirmed. Check saved status before resuming.");
    } catch (caught) {
      if (!controller.signal.aborted && !terminal) {
        dispatch({ type: "connection-failed", error: (caught as Error).message, start: !startRequested || rejected ? "rejected" : "unconfirmed" });
      }
    } finally { busy.current = false; if (!controller.signal.aborted) setStreaming(false); }
  }, [active, configured, mode, project, router, lastRun, status, refreshReadiness]);
  const stop = async (): Promise<void> => {
    if (state.phase !== "running" || !lastRun?.jobId) return;
    dispatch({ type: "stop-requested" });
    try {
      const response = await fetch("/api/pipeline/run", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, jobId: lastRun.jobId }) });
      if (!response.ok) throw new Error(await responseError(response));
      const result = await response.json() as { run: StoredRun };
      dispatch({ type: "stop-accepted", run: result.run });
    } catch (caught) { dispatch({ type: "stop-failed", error: (caught as Error).message }); }
  };
  // The card shows only while a run needs attention: running, stopped short, or refused. The landing page has no run
  // controls, so it never shows there.
  const landing = localPath(usePathname() ?? "") === "/welcome";
  const needed = active || status === "failed" || status === "interrupted" || Boolean(error);
  const panel = mode === "api" && !landing && needed && <aside className={styles.status} aria-label="API pipeline status" aria-busy={active}>
      <div className={styles.summary}><strong>{active ? state.phase === "starting" ? "Starting pipeline" : state.phase === "stopping" ? "Pipeline stopping" : "Pipeline running" : status ? `Pipeline ${status}` : "API Mode"}</strong>
        <p role="status">{message || (configured ? "Your model setup is saved. Run a stage when ready." : "Choose the models for each step before running the pipeline.")}</p>
        {lastRun?.jobId && <ApiRunMetadata run={lastRun} now={now} prompt={runPrompt} />}
        {active && <p>You can inspect other steps while this runs. Leaving this project interrupts the connection; completed checkpoints are retained.</p>}
        {!active && readiness && !readiness.modelCalls.available && <p>{readiness.modelCalls.reason}</p>}
        {!active && readinessError && <p role="alert">{readinessError}</p>}
        {error && <p className={styles.error} role="alert">{error}</p>}
      </div>
      <div className={styles.tools}>
        {!streaming && <button className={styles.button} type="button" onClick={() => void recover()}>Check saved status</button>}
        {!active && <button className={styles.button} type="button" onClick={() => void refreshReadiness()}>Check availability</button>}
        {active && lastRun?.jobId && <button className={styles.button} type="button" disabled={state.phase !== "running"} onClick={() => void stop()}>{state.phase === "stopping" ? "Stopping…" : state.phase === "requesting-stop" ? "Requesting stop…" : "Stop after current call"}</button>}
      </div>
      {(status === "interrupted" || status === "failed") && lastRun?.jobId && !active && <ApiRunRecovery project={project} jobId={lastRun.jobId} prompt={lastRun.action.prompt === undefined ? null : runPrompt ?? { state: "loading", id: lastRun.action.prompt }} busy={active} onResume={ticket => run(lastRun.action, ticket)} onRefresh={recover} />}
    </aside>;
  const context = { project, mode, configured, run, active, status, error, readiness, readinessError, openSetup, panel };
  return <Context value={context}>
    {children}
    {setupMounted && <Suspense fallback={null}><ModelSetupPopup open={setupOpen} onClose={() => setSetupOpen(false)} /></Suspense>}
  </Context>;
}

export function ApiModeContent({ project, api, children }: { project: string; api: ReactNode; children: ReactNode }): ReactElement {
  const execution = useApiExecution();
  return <>{execution?.mode === "api" && execution.project === project ? api : children}</>;
}

export function ApiStageAction({ project, action, label, prompt, lead, copyLabel, miniCopy, apiLead, beforeRun, blocked }: { project: string; action: ApiPipelineAction; label: string; prompt: string; lead?: string; copyLabel?: string; miniCopy?: boolean; apiLead?: string; beforeRun?: () => void; blocked?: string }): ReactElement {
  const execution = useApiExecution();
  if (execution?.mode !== "api" || execution.project !== project || project === "__guided-uti__") return <PromptBox prompt={prompt} lead={lead} copyLabel={copyLabel} miniCopy={miniCopy} />;
  const scope = action.sourceId ? "All cases in this uploaded source." : action.draftKey ? "This saved dataset draft." : action.caseIds?.length ? `Cases: ${action.caseIds.join(", ")}.` : "All imported cases, using the configured model and trial scope.";
  const availability = execution.readiness?.[action.stage === "score" ? "scoring" : "modelCalls"];
  const unavailable = execution.readinessError ?? (!availability ? "Checking execution availability…" : !availability.available ? availability.reason : null);
  return <div className={styles.action}><p>{apiLead ?? scope}</p>
    {apiLead && <p>{scope}</p>}
    {blocked ? <><p>{blocked}</p><Link className={styles.setup} href={noharmHref("/dataset")}>Return to Dataset</Link></> : execution.configured ? <><button className={styles.button} type="button" disabled={execution.active || Boolean(unavailable)} onClick={() => { beforeRun?.(); void execution.run(action); }}>{execution.active ? "Pipeline running…" : label}</button>{unavailable && <p>{unavailable}</p>}</> : <ModelSetupLink className={styles.setup}>Set up API models</ModelSetupLink>}
  </div>;
}

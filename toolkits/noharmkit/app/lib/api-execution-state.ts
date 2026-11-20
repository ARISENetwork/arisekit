import type { ApiPipelineAction } from "./api-pipeline-action";
import type { ApiPipelineConfig } from "./api-pipeline-config";

export type RunStatus = "running" | "completed" | "failed" | "interrupted";
interface RunMetadata { startedAt?: string; finishedAt?: string; config?: ApiPipelineConfig; workerCount?: number }
export interface ApiRunEvent extends RunMetadata { type: "started" | "progress" | "checkpoint" | "result"; jobId?: string; message?: string; status?: RunStatus; error?: string; stopping?: boolean; gaps?: string[] }
export interface StoredRun extends RunMetadata { jobId: string; action: ApiPipelineAction; status: RunStatus; message?: string; error?: string; stopping?: boolean }
type ExecutionRun = Omit<StoredRun, "error" | "stopping">;
type PendingRun = Omit<ExecutionRun, "jobId">;
type ActivePhase = "running" | "requesting-stop" | "stopping";
type TerminalStatus = Exclude<RunStatus, "running">;
type StateBody =
  | { phase: "idle" | "start-failed" | "start-unconfirmed" }
  | { phase: "starting"; run: PendingRun }
  | { phase: ActivePhase; run: ExecutionRun & { status: "running" } }
  | { phase: "settled"; run: ExecutionRun & { status: TerminalStatus } };
export type ApiExecutionState = StateBody & { error: string | null };
export type ApiExecutionAction =
  | { type: "start"; action: ApiPipelineAction }
  | { type: "event"; event: ApiRunEvent }
  | { type: "load"; run: StoredRun | null }
  | { type: "connection-failed"; error: string; start: "rejected" | "unconfirmed" }
  | { type: "problem"; error: string }
  | { type: "stop-requested" }
  | { type: "stop-accepted"; run: StoredRun }
  | { type: "stop-failed"; error: string };

export const INITIAL_EXECUTION_STATE: ApiExecutionState = { phase: "idle", error: null };

export function executionActive(state: ApiExecutionState): state is Extract<ApiExecutionState, { phase: "starting" | ActivePhase }> {
  return state.phase === "starting" || state.phase === "running" || state.phase === "requesting-stop" || state.phase === "stopping";
}

export function executionRun(state: ApiExecutionState): ExecutionRun | null {
  return state.phase === "running" || state.phase === "requesting-stop" || state.phase === "stopping" || state.phase === "settled" ? state.run : null;
}

export function executionStatus(state: ApiExecutionState): RunStatus | null {
  return state.phase === "starting" ? "running" : executionRun(state)?.status ?? null;
}

export function executionMessage(state: ApiExecutionState): string {
  if (state.phase === "start-failed") return "Pipeline could not start. Correct the error below and try again.";
  if (state.phase === "start-unconfirmed") return "The start was not confirmed. Check saved status before trying again.";
  return "run" in state ? state.run.message ?? "" : "";
}

function loadedRun(saved: StoredRun): ApiExecutionState {
  const { error, stopping, ...run } = saved;
  return run.status === "running"
    ? { phase: stopping ? "stopping" : "running", run: { ...run, status: "running" }, error: error ?? null }
    : { phase: "settled", run: { ...run, status: run.status }, error: error ?? null };
}

export function apiExecutionReducer(state: ApiExecutionState, action: ApiExecutionAction): ApiExecutionState {
  switch (action.type) {
    case "start":
      return executionActive(state) ? state : { phase: "starting", run: { action: action.action, status: "running", message: action.action.stage === "score" ? "Starting local scoring…" : "Starting pipeline…" }, error: null };
    case "load":
      return action.run ? loadedRun(action.run) : INITIAL_EXECUTION_STATE;
    case "problem":
      return { ...state, error: action.error };
    case "connection-failed": {
      if (!executionActive(state)) return state;
      const run = executionRun(state);
      return run
        ? { phase: "settled", run: { ...run, status: "interrupted" }, error: action.error }
        : { phase: action.start === "rejected" ? "start-failed" : "start-unconfirmed", error: action.error };
    }
    case "event": {
      if (!executionActive(state) || !("run" in state)) return state;
      const { type, error, stopping, ...fields } = action.event;
      const run = { ...state.run, ...fields, action: state.run.action };
      if (type === "result") {
        if (!run.jobId) return { phase: "start-failed", error: error ?? state.error };
        const status: TerminalStatus = fields.status === "completed" || fields.status === "failed" || fields.status === "interrupted" ? fields.status : error ? "failed" : "interrupted";
        return loadedRun({ ...run, jobId: run.jobId, status, error: error ?? state.error ?? undefined });
      }
      if (!run.jobId) return { phase: "starting", run, error: error ?? state.error };
      const phase = stopping === true ? "stopping" : stopping === false ? "running" : state.phase === "starting" ? "running" : state.phase;
      return { phase, run: { ...run, jobId: run.jobId, status: "running" }, error: error ?? state.error };
    }
    case "stop-requested":
      return state.phase === "running" ? { ...state, phase: "requesting-stop", error: null } : state;
    case "stop-accepted": {
      const run = executionRun(state);
      if (!executionActive(state) || !run || run.jobId !== action.run.jobId) return state;
      return { phase: action.run.stopping ? "stopping" : "running", run: { ...run, status: "running", message: action.run.message ?? "Stopping after the current call and its saved checkpoint." }, error: state.error };
    }
    case "stop-failed":
      return state.phase === "requesting-stop" || state.phase === "running" || state.phase === "stopping" ? { ...state, phase: state.phase === "requesting-stop" ? "running" : state.phase, error: action.error } : state;
  }
}

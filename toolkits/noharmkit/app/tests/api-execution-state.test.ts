import assert from "node:assert/strict";
import test from "node:test";
import { apiExecutionReducer, executionActive, executionMessage, executionRun, executionStatus, INITIAL_EXECUTION_STATE, type ApiExecutionState, type ApiRunEvent, type StoredRun } from "../lib/api-execution-state";

const saved: StoredRun = { jobId: "job-1", action: { stage: "responses" }, status: "running", startedAt: "2026-10-26T12:00:00Z", message: "Collecting responses" };
const start = (): ApiExecutionState => apiExecutionReducer(INITIAL_EXECUTION_STATE, { type: "start", action: saved.action });
const event = (state: ApiExecutionState, value: ApiRunEvent): ApiExecutionState => apiExecutionReducer(state, { type: "event", event: value });

test("a rejected start and an unconfirmed start have no recoverable job and both permit a clean retry", () => {
  for (const outcome of ["rejected", "unconfirmed"] as const) {
    const failed = apiExecutionReducer(start(), { type: "connection-failed", start: outcome, error: outcome === "rejected" ? "Missing API key" : "Connection lost" });
    assert.equal(executionActive(failed), false);
    assert.equal(executionStatus(failed), null);
    assert.equal(executionRun(failed), null);
    assert.match(executionMessage(failed), outcome === "rejected" ? /could not start/ : /not confirmed.*Check saved status/);
    const retry = apiExecutionReducer(failed, { type: "start", action: { stage: "score" } });
    assert.equal(executionActive(retry), true);
    assert.equal(retry.error, null);
    assert.equal(executionRun(retry), null);
    assert.equal(executionMessage(retry), "Starting local scoring…");
  }
});

test("events retain one run identity and its metadata through progress, a saved checkpoint, and interruption", () => {
  let state = event(start(), { type: "started", jobId: saved.jobId, startedAt: saved.startedAt, workerCount: 2 });
  state = event(state, { type: "progress", message: "Collecting case two" });
  state = event(state, { type: "checkpoint", message: "Case two saved" });
  const failed = apiExecutionReducer(state, { type: "connection-failed", start: "unconfirmed", error: "Connection lost after checkpoint" });
  assert.equal(executionActive(failed), false);
  assert.equal(executionStatus(failed), "interrupted");
  assert.deepEqual(executionRun(failed), { action: saved.action, status: "interrupted", jobId: saved.jobId, startedAt: saved.startedAt, workerCount: 2, message: "Case two saved" });
  assert.equal(failed.error, "Connection lost after checkpoint");
  assert.equal(executionMessage(failed), "Case two saved");
});

test("stop stays active through confirmation and checkpoints, then settles without a stop control", () => {
  let state = apiExecutionReducer(INITIAL_EXECUTION_STATE, { type: "load", run: saved });
  state = apiExecutionReducer(state, { type: "stop-requested" });
  assert.equal(state.phase, "requesting-stop");
  assert.equal(executionActive(state), true);
  state = event(state, { type: "progress", stopping: true, message: "Stopping after the current call" });
  assert.equal(state.phase, "stopping");
  state = apiExecutionReducer(state, { type: "stop-accepted", run: { ...saved, stopping: true, message: "Stopping after the current call" } });
  state = event(state, { type: "checkpoint", message: "Current call saved" });
  assert.equal(state.phase, "stopping");
  assert.equal(executionStatus(state), "running");
  state = event(state, { type: "result", status: "interrupted", finishedAt: "2026-10-26T12:00:10Z", message: "Stopped after saving the current checkpoint" });
  assert.equal(state.phase, "settled");
  assert.equal(executionActive(state), false);
  assert.equal(executionStatus(state), "interrupted");
  assert.match(executionMessage(state), /Stopped after saving/);
});

test("a failed stop returns to running and a later server confirmation still establishes stopping", () => {
  let state = apiExecutionReducer(INITIAL_EXECUTION_STATE, { type: "load", run: saved });
  state = apiExecutionReducer(state, { type: "stop-requested" });
  state = apiExecutionReducer(state, { type: "stop-failed", error: "Stop request disconnected" });
  assert.equal(state.phase, "running");
  assert.equal(state.error, "Stop request disconnected");
  state = event(state, { type: "progress", stopping: true });
  assert.equal(state.phase, "stopping");
  assert.equal(executionActive(state), true);
});

test("terminal results cannot be overwritten by a delayed stop response, stream update, or transport failure", () => {
  let state = event(start(), { type: "started", jobId: saved.jobId });
  state = apiExecutionReducer(state, { type: "stop-requested" });
  state = event(state, { type: "result", status: "completed", message: "All outputs saved" });
  assert.equal(apiExecutionReducer(state, { type: "stop-accepted", run: { ...saved, stopping: true } }), state);
  assert.equal(apiExecutionReducer(state, { type: "stop-failed", error: "This run is no longer active" }), state);
  assert.equal(event(state, { type: "progress", stopping: true, message: "Stopping" }), state);
  assert.equal(apiExecutionReducer(state, { type: "connection-failed", start: "unconfirmed", error: "Late disconnect" }), state);
  assert.equal(executionStatus(state), "completed");
  assert.equal(executionMessage(state), "All outputs saved");
  assert.equal(executionActive(state), false);
});

test("saved-status checks restore stopping and terminal errors, and an empty check clears obsolete notices", () => {
  let state = apiExecutionReducer(INITIAL_EXECUTION_STATE, { type: "load", run: { ...saved, stopping: true } });
  assert.equal(state.phase, "stopping");
  assert.equal(executionActive(state), true);
  state = apiExecutionReducer(state, { type: "load", run: { ...saved, status: "failed", error: "Provider quota exhausted" } });
  assert.equal(executionStatus(state), "failed");
  assert.equal(executionActive(state), false);
  assert.equal(state.error, "Provider quota exhausted");
  state = apiExecutionReducer(state, { type: "problem", error: "Saved status could not be fetched" });
  assert.equal(executionStatus(state), "failed");
  assert.equal(executionRun(state)?.jobId, saved.jobId);
  assert.equal(state.error, "Saved status could not be fetched");
  assert.deepEqual(apiExecutionReducer(state, { type: "load", run: null }), INITIAL_EXECUTION_STATE);
});

test("a server rejection before a job ID does not invent saved work, and duplicate start cannot erase an active job", () => {
  const failed = event(start(), { type: "result", status: "failed", error: "Inputs changed before execution" });
  assert.equal(failed.phase, "start-failed");
  assert.equal(executionRun(failed), null);
  assert.equal(executionActive(failed), false);
  assert.equal(failed.error, "Inputs changed before execution");
  const running = event(start(), { type: "started", jobId: saved.jobId });
  assert.equal(apiExecutionReducer(running, { type: "start", action: { stage: "judge" } }), running);
  const pending = apiExecutionReducer(running, { type: "stop-requested" });
  assert.equal(apiExecutionReducer(pending, { type: "stop-accepted", run: { ...saved, jobId: "different-job", stopping: true } }), pending);
});

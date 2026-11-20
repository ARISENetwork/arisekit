import { randomUUID } from "node:crypto";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import { KIT_ROOT, inside } from "@/lib/caseset/paths";
import type { ApiPipelineAction } from "@/lib/api-pipeline-action";
import type { ApiPipelineConfig } from "@/lib/api-pipeline-config";
import { inspectPipeline, pipelineRequest, type PipelineInspection } from "./pipeline-inspection";
import { updateWorkspaceWorker } from "./pipeline-workspace-state";
import { readPipelineRecord, writePipelineRecord, type PipelineWorkspace } from "@/lib/pipeline-workspace";

export interface PipelineRunRecord {
  jobId: string;
  action: ApiPipelineAction;
  config: ApiPipelineConfig;
  status: "running" | "completed" | "failed" | "interrupted";
  startedAt: string;
  finishedAt?: string;
  message: string;
  error?: string;
  executionDirectory: string;
  operationIdentity?: string;
  recoveredFrom?: string;
  route?: "local" | "openrouter";
  stopping?: boolean;
  gaps?: string[];
}
export interface PipelineEvent { type: "started" | "progress" | "checkpoint" | "result"; jobId?: string; message?: string; status?: PipelineRunRecord["status"]; error?: string; startedAt?: string; finishedAt?: string; stage?: ApiPipelineAction["stage"]; config?: ApiPipelineConfig; route?: PipelineRunRecord["route"]; stopping?: boolean; gaps?: string[] }

const state = globalThis as typeof globalThis & { __noharmApiRuns?: Map<string, PipelineRunRecord>; __noharmApiStops?: Map<string, () => void> };
const active = state.__noharmApiRuns ??= new Map<string, PipelineRunRecord>();
const stops = state.__noharmApiStops ??= new Map<string, () => void>();

export function pipelineActive(key: string): boolean { return active.has(key); }

export function stopPipelineRun(key: string, jobId: string): PipelineRunRecord {
  const run = active.get(key);
  if (!run || run.jobId !== jobId || !stops.has(key)) throw new Error("This run is no longer active. Check saved status before continuing.");
  stops.get(key)!();
  return run;
}

export function currentPipelineRun(directory: string, key?: string): PipelineRunRecord | null {
  const saved = readPipelineRecord<PipelineRunRecord>(directory, "latest.json");
  if (key && active.has(key)) return active.get(key)!;
  return saved?.status === "running" ? { ...saved, status: "failed", error: `Execution stopped before its final status was saved. Inspect retained output at ${saved.executionDirectory} before retrying.`, message: "The previous execution has an unresolved final status." } : saved;
}

export function pipelinePython(): string {
  const candidates = [process.env.NOHARM_PIPELINE_PYTHON, path.resolve(KIT_ROOT, "../../.venv/bin/python"), path.resolve(KIT_ROOT, "../../scripts/dev/.venv/bin/python"), path.join(KIT_ROOT, ".venv/bin/python")];
  const python = candidates.find(candidate => candidate && existsSync(candidate));
  if (!python || !existsSync(path.join(KIT_ROOT, "tools", "web_pipeline.py"))) throw new Error("The Python pipeline runtime is unavailable. Install the project runtime or configure NOHARM_PIPELINE_PYTHON before running.");
  return python;
}

export async function executePipeline(workspace: PipelineWorkspace, action: ApiPipelineAction, config: ApiPipelineConfig, options: {
  apiKey: string;
  signal: AbortSignal;
  emit: (event: PipelineEvent) => void;
  python?: string;
  driver?: string;
  inspect?: (workspace: PipelineWorkspace, action: ApiPipelineAction, config: ApiPipelineConfig, python: string) => Promise<PipelineInspection>;
  recoveredFrom?: string;
}): Promise<PipelineRunRecord> {
  if (active.has(workspace.key)) throw new Error("A pipeline step is already running for this project.");
  const previous = readPipelineRecord<PipelineRunRecord>(workspace.directory, "latest.json");
  if (previous?.status === "running" && options.recoveredFrom !== previous.jobId) throw new Error(`The previous run has an unresolved final status. Review saved work before retrying. No new model call was made.`);
  const python = options.python ?? pipelinePython();
  const inspection = await (options.inspect ?? inspectPipeline)(workspace, action, config, python);
  if (inspection.status !== "ready") throw new Error(inspection.reason ?? "The saved stage cannot be resumed. Review saved work before continuing.");
  if (active.has(workspace.key)) throw new Error("A pipeline step is already running for this project.");
  const requested = pipelineRequest(workspace, action, config);
  const record: PipelineRunRecord = { jobId: randomUUID(), action, config, status: "running", startedAt: new Date().toISOString(), executionDirectory: workspace.directory, route: action.stage === "score" ? "local" : "openrouter", message: action.stage === "score" ? "Computing scores locally. Deterministic; no model calls or API credits." : `Running ${action.stage} through OpenRouter.` };
  active.set(workspace.key, record);
  record.operationIdentity = inspection.operationIdentity;
  if (options.recoveredFrom) record.recoveredFrom = options.recoveredFrom;
  const save = async (): Promise<void> => {
    writePipelineRecord(workspace.directory, "latest.json", record);
    writePipelineRecord(workspace.directory, `${record.jobId}.json`, record);
    await workspace.publish();
  };
  let child: ChildProcessWithoutNullStreams | undefined;
  let processDone: Promise<number | null> | undefined;
  let inputError: Error | undefined;
  let interrupted = options.signal.aborted;
  const interrupt = (): void => { interrupted = true; };
  options.signal.addEventListener("abort", interrupt, { once: true });
  stops.set(workspace.key, () => {
    interrupted = true;
    record.stopping = true;
    record.message = "Stopping after the current call and its saved checkpoint. The current call may still use API credits.";
    options.emit({ type: "progress", jobId: record.jobId, status: "running", stopping: true, message: record.message });
  });
  try {
    if (interrupted) throw new Error("The pipeline request was interrupted before execution.");
    await save();
    options.emit({ type: "started", jobId: record.jobId, status: record.status, startedAt: record.startedAt, message: record.message, stage: action.stage, config, route: record.route });
    if (interrupted) throw new Error("The pipeline request was interrupted before execution.");
    updateWorkspaceWorker(workspace.directory, workspace.project, workspace.key, record.jobId, { state: "starting" });
    child = spawn(python, ["-u", options.driver ?? path.join(KIT_ROOT, "tools", "web_pipeline.py")], {
      cwd: KIT_ROOT, shell: false, stdio: ["pipe", "pipe", "pipe"],
      env: { NODE_ENV: process.env.NODE_ENV, PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, PYTHONUNBUFFERED: "1", OPENROUTER_API_KEY: options.apiKey },
    });
    if (child.pid) updateWorkspaceWorker(workspace.directory, workspace.project, workspace.key, record.jobId, { state: "running", pid: child.pid });
    processDone = new Promise<number | null>((resolve, reject) => { child!.once("error", reject); child!.once("close", resolve); });
    // Attach a handler before reading stdout so spawn errors cannot become unhandled rejections.
    void processDone.catch(() => {});
    child.stdin.on("error", (error: Error) => { inputError = error; child?.kill("SIGTERM"); });
    const logFolder = inside(workspace.directory, "web-execution", "logs");
    mkdirSync(logFolder, { recursive: true, mode: 0o700 });
    const logFile = inside(logFolder, `${record.jobId}.log`);
    child.stderr.on("data", (chunk: Buffer) => {
      appendFileSync(logFile, chunk, { mode: 0o600 });
      options.emit({ type: "progress", jobId: record.jobId, message: chunk.toString("utf8").trim() });
    });
    child.stdin.write(`${JSON.stringify(requested)}\n`);
    let result: { status: string; errors?: string[]; gaps?: string[] } | undefined;
    for await (const line of createInterface({ input: child.stdout })) {
      const event = JSON.parse(line) as { type: string; status?: string; errors?: string[]; gaps?: string[]; stage?: string; message?: string };
      if (event.type === "checkpoint") {
        record.message = event.message ?? `Saved ${event.stage ?? action.stage} checkpoint.`;
        await save();
        options.emit({ type: "checkpoint", jobId: record.jobId, message: record.message });
        if (interrupted) throw new Error(record.stopping ? "Stopped after saving the current checkpoint. Completed outputs are retained." : "The pipeline request was interrupted after its last saved checkpoint.");
        child.stdin.write('{"type":"ack"}\n');
      } else if (event.type === "result") result = { status: event.status ?? "failed", errors: event.errors, gaps: event.gaps };
      else throw new Error(`Unexpected pipeline event: ${event.type}.`);
    }
    const exitCode = await processDone;
    if (inputError) throw inputError;
    if (interrupted) throw new Error(record.stopping ? "Stopped. Completed checkpoints were preserved." : "The pipeline request was interrupted. Completed checkpoints were preserved.");
    if (exitCode !== 0 || result?.status !== "completed") throw new Error(result?.errors?.join("\n") || `Pipeline exited with code ${exitCode} without a completed result.`);
    record.status = "completed";
    if (result?.gaps?.length) record.gaps = result.gaps;
    record.message = action.stage === "score" ? `Scores completed locally. No model calls or API credits were used. Outputs are saved.${record.gaps ? ` ${record.gaps.length} coverage ${record.gaps.length === 1 ? "gap remains" : "gaps remain"}: ${record.gaps.join("; ")}` : ""}` : `${action.stage} completed. Outputs are saved.`;
  } catch (caught) {
    child?.kill("SIGTERM");
    record.status = interrupted ? "interrupted" : "failed";
    record.error = (caught as Error).message;
    record.message = record.error;
  } finally {
    if (child && child.exitCode === null) child.kill("SIGTERM");
    if (processDone) await processDone.catch(() => {});
    updateWorkspaceWorker(workspace.directory, workspace.project, workspace.key, record.jobId, { state: "exited" });
    record.finishedAt = new Date().toISOString();
    record.stopping = false;
    options.signal.removeEventListener("abort", interrupt);
    try { await save(); }
    catch (caught) {
      record.status = "failed";
      record.error = `${(caught as Error).message} Execution files are retained at ${workspace.directory}.`;
      record.message = record.error;
      writePipelineRecord(workspace.directory, "latest.json", record);
    }
    active.delete(workspace.key);
    stops.delete(workspace.key);
    options.emit({ type: "result", jobId: record.jobId, status: record.status, message: record.message, error: record.error, startedAt: record.startedAt, finishedAt: record.finishedAt, route: record.route, ...(record.gaps ? { gaps: record.gaps } : {}) });
  }
  return record;
}

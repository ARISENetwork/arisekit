import { randomUUID } from "node:crypto";
import { writeFileSync } from "node:fs";
import path from "node:path";
import type { ApiPipelineConfig } from "./api-pipeline-config";
import type { ProjectFiles } from "./project-files";
import { filesIn } from "./project-files";
import { casesetDir, inside } from "./caseset/paths";
import { createProject } from "./project-create";
import { materializeProject, readPipelineRecord, type PipelineWorkspace } from "./pipeline-workspace";
import { fileHashes, projectFingerprint, readWorkspaceState, workerStopped } from "./pipeline-workspace-state";
import { inspectPipelineFiles } from "./pipeline-inspection";
import { pipelineActive, type PipelineRunRecord } from "./pipeline-runner";

export interface RecoveryTicket { jobId: string; token: string }
export interface RecoveryPlan {
  status: "ready" | "new-run" | "running" | "completed" | "blocked";
  jobId: string;
  token?: string;
  reason: string;
  reusableCalls: number;
  pending?: boolean;
  restoredFiles: number;
  suggestedName?: string;
}
interface RecoveryInspection { plan: RecoveryPlan; files: ProjectFiles; originFingerprint: string; record: PipelineRunRecord | null }
type Inspect = typeof inspectPipelineFiles;

export function mergeRetainedFiles(current: ProjectFiles, retained: ProjectFiles, base: Record<string, string>): { files: ProjectFiles; conflicts: string[]; restored: number } {
  const files = { ...current };
  const currentHashes = fileHashes(current), retainedHashes = fileHashes(retained);
  const conflicts: string[] = [];
  let restored = 0;
  for (const name of new Set([...Object.keys(base), ...Object.keys(retained)])) {
    if (name.endsWith("/")) continue;
    if (retainedHashes[name] === base[name]) continue;
    if (retainedHashes[name] === undefined || currentHashes[name] !== base[name] && currentHashes[name] !== retainedHashes[name]) { conflicts.push(name); continue; }
    if (currentHashes[name] !== retainedHashes[name]) { files[name] = retained[name]; restored++; }
  }
  return { files, conflicts, restored };
}

export async function inspectRecovery(directory: string, key: string, config: ApiPipelineConfig, python: string, inspect: Inspect = inspectPipelineFiles): Promise<RecoveryInspection> {
  const current = filesIn(directory);
  const originFingerprint = projectFingerprint(current);
  const record = readPipelineRecord<PipelineRunRecord>(directory, "latest.json");
  const base = { jobId: record?.jobId ?? "", reusableCalls: 0, restoredFiles: 0 };
  const finish = (plan: RecoveryPlan, files: ProjectFiles = current): RecoveryInspection => ({ plan, files, originFingerprint, record });
  if (!record) return finish({ ...base, status: "blocked", reason: "There is no saved run to recover." });
  if (pipelineActive(key)) return finish({ ...base, status: "running", reason: "This run is still active. No new run or model call was started." });
  if (record.status === "completed") return finish({ ...base, status: "completed", reason: "This stage already completed. Its outputs are saved." });
  let retained: ProjectFiles;
  let merged: ReturnType<typeof mergeRetainedFiles>;
  try {
    const state = readWorkspaceState(record.executionDirectory, path.basename(directory), key);
    if (!state || state.jobId !== record.jobId) return finish({ ...base, status: "blocked", reason: "This older run has no verifiable recovery record. Its files are preserved; inspect the retained execution before retrying." });
    if (!workerStopped(state)) return finish({ ...base, status: "running", reason: "The previous worker is still active or its state cannot be verified. Check saved status again before retrying." });
    const saved = readPipelineRecord<PipelineRunRecord>(record.executionDirectory, "latest.json");
    if (saved?.jobId !== record.jobId) throw new Error("The retained execution no longer matches this run.");
    retained = filesIn(record.executionDirectory);
    merged = mergeRetainedFiles(current, retained, state.base);
  } catch (error) {
    return finish({ ...base, status: "blocked", reason: (error as Error).message });
  }
  const token = projectFingerprint({ origin: originFingerprint, retained: projectFingerprint(retained), config: JSON.stringify(config), job: record.jobId });
  const fresh = { ...base, token, suggestedName: `${path.basename(directory).slice(0, 44)}-retry-${record.jobId.slice(0, 8)}` };
  if (merged.conflicts.length) return finish({ ...fresh, status: "new-run", reason: `The current project and retained execution both changed: ${merged.conflicts.join(", ")}. Start a new run to preserve both versions.` });
  const result = await inspect(merged.files, path.basename(directory), record.action, config, python);
  if (result.status !== "ready" || !record.operationIdentity || result.operationIdentity !== record.operationIdentity) return finish({ ...fresh, status: "new-run", reason: result.reason ?? "Inputs, models, prompts, or execution rules changed. Start a new run; the original outputs will remain intact." });
  return finish({ ...fresh, status: "ready", reusableCalls: result.reusableCalls, pending: result.pending, restoredFiles: merged.restored, reason: result.pending ? "Saved work matches this stage. Resume will reuse verified outputs and run only the remaining calls." : "Saved work matches this stage. Resume can finish from the verified outputs." }, merged.files);
}

export function requireRecoveryTicket(inspection: RecoveryInspection, ticket: RecoveryTicket): void {
  if (ticket.jobId !== inspection.plan.jobId || !inspection.plan.token || ticket.token !== inspection.plan.token) throw new Error("The run changed after inspection. Review saved work again before continuing.");
}

export function restoreRecovery(workspace: PipelineWorkspace, inspection: RecoveryInspection, ticket: RecoveryTicket): void {
  requireRecoveryTicket(inspection, ticket);
  if (inspection.plan.status !== "ready" || !inspection.record) throw new Error("This run cannot be resumed from the saved work.");
  if (projectFingerprint(filesIn(workspace.directory)) !== inspection.originFingerprint) throw new Error("The project changed after inspection. Review saved work again.");
  materializeProject(workspace.directory, inspection.files);
  const folder = inside(workspace.directory, "web-execution");
  const manifest = inside(folder, `recovery-${randomUUID()}.json`);
  writeFileSync(manifest, `${JSON.stringify({ sourceJob: inspection.record, inspectedAt: new Date().toISOString(), originFingerprint: inspection.originFingerprint, restoredFiles: inspection.plan.restoredFiles, reusableCalls: inspection.plan.reusableCalls }, null, 2)}\n`, { flag: "wx", mode: 0o600 });
}

export function newRecoveryRun(root: string, source: string, name: string, inspection: RecoveryInspection, ticket: RecoveryTicket, config: ApiPipelineConfig): void {
  requireRecoveryTicket(inspection, ticket);
  if (inspection.plan.status !== "new-run" || !inspection.record) throw new Error("This run does not require a fresh project run.");
  const original = casesetDir(root, source);
  if (projectFingerprint(filesIn(original)) !== inspection.originFingerprint) throw new Error("The project changed after inspection. Review saved work again.");
  const stage = inspection.record.action.stage;
  const files = filesIn(original);
  const provenance = JSON.parse(Buffer.from(files["provenance.json"], "base64").toString("utf8")) as Record<string, unknown>;
  createProject(root, name, String(provenance.description ?? ""), "api");
  const copied: ProjectFiles = {};
  for (const [file, bytes] of Object.entries(files)) {
    const input = file === "items.jsonl" || file === "prompts.json" || file.startsWith("cases/") || file.startsWith("imports/") || file.startsWith("dataset-drafts");
    const rubric = stage !== "generate" && file.startsWith("answer-tables/");
    const responses = (stage === "judge" || stage === "score") && file.startsWith("results/responses/");
    const judgments = stage === "score" && (file.startsWith("results/judge/") || file.startsWith("web-execution/judge-"));
    if (input || rubric || responses || judgments) copied[file] = bytes;
  }
  const now = new Date().toISOString();
  const { models: _models, inference: _inference, ...sourceProvenance } = provenance;
  const keepResponses = stage === "judge" || stage === "score";
  copied["provenance.json"] = Buffer.from(`${JSON.stringify({ ...sourceProvenance, ...(keepResponses ? { models: provenance.models, inference: provenance.inference } : {}), caseset_name: name, execution_mode: "api", created_at: now, updated_at: now, recovery_source: { project: source, jobId: inspection.record.jobId, stage, sourceFingerprint: inspection.originFingerprint } }, null, 2)}\n`).toString("base64");
  copied["api-pipeline.json"] = Buffer.from(`${JSON.stringify(config, null, 2)}\n`).toString("base64");
  copied["recovery-source.json"] = Buffer.from(`${JSON.stringify({ project: source, jobId: inspection.record.jobId, copiedFiles: fileHashes(copied), reason: inspection.plan.reason, createdAt: now }, null, 2)}\n`).toString("base64");
  materializeProject(path.join(root, name), copied);
}

import { createHash, randomUUID } from "node:crypto";
import { existsSync, lstatSync, readFileSync, realpathSync, renameSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { ProjectFiles } from "./project-files";

export interface WorkspaceState {
  version: 1;
  key: string;
  project: string;
  base: Record<string, string>;
  jobId?: string;
  worker: { state: "not-started" | "starting" | "running" | "exited"; pid?: number };
}

export function fileHashes(files: ProjectFiles): Record<string, string> {
  return Object.fromEntries(Object.entries(files).map(([name, bytes]) => [name, createHash("sha256").update(Buffer.from(bytes, "base64")).digest("hex")]));
}

export function projectFingerprint(files: ProjectFiles): string {
  return createHash("sha256").update(JSON.stringify(Object.entries(files).sort(([a], [b]) => a.localeCompare(b)))).digest("hex");
}

export function managedExecutionDirectory(directory: string, project: string): string {
  if (directory.toLowerCase().includes("holdout")) throw new Error("The execution path is excluded.");
  const folder = path.dirname(directory);
  if (path.basename(directory) !== project || !/^arisekit-pipeline-[A-Za-z0-9]+$/.test(path.basename(folder))) throw new Error("The retained execution path is not a managed workspace.");
  if (lstatSync(folder).isSymbolicLink() || lstatSync(directory).isSymbolicLink() || path.dirname(realpathSync(folder)) !== realpathSync(os.tmpdir())) throw new Error("The retained execution path is not a managed workspace.");
  return realpathSync(directory);
}

export function readWorkspaceState(directory: string, project: string, key: string): WorkspaceState | null {
  const managed = managedExecutionDirectory(directory, project);
  const file = path.join(path.dirname(managed), ".execution-state.json");
  if (!existsSync(file)) return null;
  if (lstatSync(file).isSymbolicLink()) throw new Error("The execution ownership record cannot be a link.");
  const state = JSON.parse(readFileSync(file, "utf8")) as WorkspaceState;
  if (state.version !== 1 || state.project !== project || state.key !== key) throw new Error("The retained execution belongs to another workspace.");
  return state;
}

export function writeWorkspaceState(directory: string, state: WorkspaceState): void {
  const folder = path.dirname(managedExecutionDirectory(directory, state.project));
  const temporary = path.join(folder, `${randomUUID()}.tmp`);
  writeFileSync(temporary, `${JSON.stringify(state)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, path.join(folder, ".execution-state.json"));
}

export function updateWorkspaceWorker(directory: string, project: string, key: string, jobId: string, worker: WorkspaceState["worker"]): void {
  const state = readWorkspaceState(directory, project, key);
  if (!state) throw new Error("The execution ownership record is missing.");
  writeWorkspaceState(directory, { ...state, jobId, worker });
}

export function workerStopped(state: WorkspaceState): boolean {
  if (state.worker.state === "exited" || state.worker.state === "not-started") return true;
  if (state.worker.state !== "running" || !Number.isInteger(state.worker.pid) || state.worker.pid! < 1) return false;
  try { process.kill(state.worker.pid!, 0); return false; }
  catch (error) { return (error as NodeJS.ErrnoException).code === "ESRCH"; }
}

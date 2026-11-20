import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { filesIn, ProjectFileError, type ProjectFiles } from "@/lib/project-files";
import { casesetDir, inside, projectsRoot } from "@/lib/caseset/paths";
import { fileHashes, readWorkspaceState, writeWorkspaceState } from "./pipeline-workspace-state";

function fingerprint(files: ProjectFiles): string {
  return createHash("sha256").update(JSON.stringify(Object.entries(files).sort(([a], [b]) => a.localeCompare(b)))).digest("hex");
}

export function materializeProject(folder: string, files: ProjectFiles): void {
  mkdirSync(folder, { recursive: true, mode: 0o700 });
  for (const [name, bytes] of Object.entries(files)) {
    if (name.endsWith("/")) { mkdirSync(inside(folder, ...name.slice(0, -1).split("/")), { recursive: true, mode: 0o700 }); continue; }
    const file = inside(folder, ...name.split("/"));
    mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
    const temporary = inside(folder, `${name}.${randomUUID()}.tmp`);
    writeFileSync(temporary, Buffer.from(bytes, "base64"), { flag: "wx", mode: 0o600 });
    renameSync(temporary, file);
  }
}

export interface PipelineWorkspace {
  key: string;
  root: string;
  project: string;
  directory: string;
  publish: () => Promise<void>;
}

export function localPipelineWorkspace(root: string, project: string): PipelineWorkspace {
  const original = casesetDir(root, project);
  const base = filesIn(original);
  let previous = fingerprint(base);
  const jobRoot = mkdtempSync(path.join(os.tmpdir(), "arisekit-pipeline-"));
  const directory = path.join(jobRoot, project);
  materializeProject(directory, base);
  writeWorkspaceState(directory, { version: 1, key: `local:${original}`, project, base: fileHashes(base), worker: { state: "not-started" } });
  return { key: `local:${original}`, root: jobRoot, project, directory, publish: async (): Promise<void> => {
    const latest = filesIn(original);
    if (fingerprint(latest) !== previous) throw new ProjectFileError("The project changed during execution. Generated artifacts were retained in the execution workspace; reload before continuing.", 409);
    const next = filesIn(directory);
    const removed = Object.keys(latest).filter(name => !name.endsWith("/") && !Object.hasOwn(next, name));
    if (removed.length) throw new ProjectFileError(`The pipeline tried to remove project files: ${removed.join(", ")}. Existing files were preserved.`, 409);
    const changed = Object.fromEntries(Object.entries(next).filter(([name, bytes]) => latest[name] !== bytes));
    materializeProject(original, changed);
    previous = fingerprint(filesIn(original));
    const state = readWorkspaceState(directory, project, `local:${original}`)!;
    writeWorkspaceState(directory, { ...state, base: fileHashes(filesIn(original)) });
  } };
}

export function createPipelineWorkspace(project: string): PipelineWorkspace {
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(project)) throw new TypeError("Choose a valid project.");
  return localPipelineWorkspace(projectsRoot(), project);
}

export function writePipelineRecord(directory: string, name: string, value: unknown): void {
  const folder = inside(directory, "web-execution");
  mkdirSync(folder, { recursive: true, mode: 0o700 });
  const temporary = inside(folder, `${randomUUID()}.tmp`);
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, inside(folder, name));
}

export function readPipelineRecord<T>(directory: string, name: string): T | null {
  const file = inside(directory, "web-execution", name);
  return existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) as T : null;
}

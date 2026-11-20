import { existsSync, lstatSync, readdirSync, realpathSync, statSync } from "node:fs";
import path from "node:path";

import { isValidReviewerId } from "@/lib/clinician-review";

// The app runs with cwd = app/, so the kit root is its parent.
export const KIT_ROOT = path.resolve(process.cwd(), "..");

const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const CASE_ID = /^[A-Za-z0-9_]+$/;
const RUN = /^run([1-9]\d*)$/;
const REVIEWED = /^reviewed-(.*)$/;
const RUN_STATUS_FILE = /^run([1-9]\d*)\.status\.json$/;
const REVIEWED_FILE = /^reviewed-([a-z0-9][a-z0-9-]{1,31})\.json$/;
const MODEL = /^[A-Za-z0-9][A-Za-z0-9._+-]*$/;

export class NotFoundError extends Error {}

export function projectsRoot(kitRoot = KIT_ROOT, env: Readonly<Record<string, string | undefined>> = process.env): string {
  const configured = env.NOHARM_PROJECTS || env.NOHARM_CASESETS;
  if (configured) return path.resolve(kitRoot, configured);
  const projects = path.join(kitRoot, "projects");
  const legacy = path.join(kitRoot, "casesets");
  const isDirectory = (folder: string): boolean => existsSync(folder) && statSync(folder).isDirectory();
  return path.resolve(isDirectory(projects) || !isDirectory(legacy) ? projects : legacy);
}

// Compatibility for integrations that still import the former name.
export const casesetsRoot = projectsRoot;

function present(p: string): boolean {
  try {
    lstatSync(p);
    return true;
  } catch {
    return false;
  }
}

// The one containment check for every read, listing, existence check, and write. The target, or for a
// target that does not exist yet its nearest existing ancestor, must resolve after symlinks inside `root`.
// A file or directory symlink pointing outside is refused, and so is a dangling link (writing through it
// would create a file wherever it points).
export function inside(root: string, ...parts: string[]): string {
  const base = realpathSync(root);
  let existing = path.resolve(base, ...parts);
  const rest: string[] = [];
  while (!present(existing)) {
    rest.unshift(path.basename(existing));
    existing = path.dirname(existing);
  }
  let real: string;
  try {
    real = path.join(realpathSync(existing), ...rest);
  } catch {
    throw new NotFoundError(`${parts.join("/")} is a dangling link`);
  }
  if (real !== base && !real.startsWith(`${base}${path.sep}`)) throw new NotFoundError(`${parts.join("/")} is outside ${base}`);
  return real;
}

// Listings through the containment check: a folder that resolves outside throws, never reads as empty.
export function list(root: string, ...parts: string[]): string[] {
  const dir = inside(root, ...parts);
  return existsSync(dir) ? readdirSync(dir) : [];
}

// Real directories only; a symlinked folder is never a project.
export function listCasesetNames(root: string): string[] {
  if (!existsSync(root)) return [];
  return readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory() && NAME.test(d.name)).map((d) => d.name).sort();
}

export function casesetDir(root: string, name: string): string {
  if (!listCasesetNames(root).includes(name)) throw new NotFoundError(`no project ${name}`);
  return inside(root, name);
}

export function caseIds(dir: string): string[] {
  return list(dir, "cases").filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).filter((id) => CASE_ID.test(id)).sort();
}

export function assertCase(dir: string, caseId: string): void {
  if (!caseIds(dir).includes(caseId)) throw new NotFoundError(`no item ${caseId}`);
}

export type Version = { kind: "run"; run: number } | { kind: "reviewed"; reviewer: string };

export function parseVersion(label: string): Version {
  const run = RUN.exec(label);
  if (run) return { kind: "run", run: Number(run[1]) };
  const reviewed = REVIEWED.exec(label);
  if (reviewed && isValidReviewerId(reviewed[1])) return { kind: "reviewed", reviewer: reviewed[1] };
  throw new NotFoundError(`no table version ${label}`);
}

// Runs by number, then reviewed copies by reviewer.
export function listVersionLabels(dir: string, caseId: string): string[] {
  const own = list(dir, "answer-tables").filter((f) => f.startsWith(`${caseId}.`)).map((f) => f.slice(caseId.length + 1));
  const runs = own.flatMap((f) => { const m = RUN_STATUS_FILE.exec(f); return m ? [Number(m[1])] : []; }).sort((a, b) => a - b).map((k) => `run${k}`);
  const reviewed = own.flatMap((f) => { const m = REVIEWED_FILE.exec(f); return m ? [`reviewed-${m[1]}`] : []; }).sort();
  return [...runs, ...reviewed];
}

export function assertVersion(dir: string, caseId: string, label: string): Version {
  const version = parseVersion(label);
  if (!listVersionLabels(dir, caseId).includes(label)) throw new NotFoundError(`${caseId} has no table ${label}`);
  return version;
}

export function listModels(dir: string): string[] {
  return list(dir, "results", "responses").filter((f) => f.endsWith(".jsonl")).map((f) => f.slice(0, -6)).filter((m) => MODEL.test(m)).sort();
}

export function assertModel(dir: string, model: string): void {
  if (!listModels(dir).includes(model)) throw new NotFoundError(`no responses for model ${model}`);
}

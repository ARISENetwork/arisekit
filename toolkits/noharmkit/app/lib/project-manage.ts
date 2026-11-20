import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { benchmarkUpdatedAt } from "@/lib/caseset/metrics";
import { casesetDir, inside } from "@/lib/caseset/paths";
import { isTutorialProject } from "@/lib/onboarding";
import type { ProjectExecutionMode } from "@/lib/project-mode";
import { readProjectMode } from "@/lib/project-mode-store";
import { readPipelineRecord } from "@/lib/pipeline-workspace";
import type { PipelineRunRecord } from "@/lib/pipeline-runner";
import { NOTE_LIMIT, TITLE_LIMIT } from "@/lib/project-manage-limits";

// A project's display name and note travel inside it, so they sync with the rest of its files. The display name only
// changes what the app shows: the folder and every record keep the project's original name.
export const INFO_FILE = "project-info.json";
// Deleted local projects move here. The leading dot keeps the folder out of the project list.
export const DELETED_FOLDER = ".deleted";

export interface ProjectInfo { title: string; note: string }
export interface ProjectRow extends ProjectInfo { name: string; mode: ProjectExecutionMode; updatedAt: string | null; locked: string | null }

export function readProjectInfo(root: string, name: string): ProjectInfo {
  const file = inside(casesetDir(root, name), INFO_FILE);
  if (!existsSync(file)) return { title: "", note: "" };
  // A hand-edited or half-synced file must not take down every page that lists projects.
  let saved: Partial<Record<keyof ProjectInfo, unknown>>;
  try { saved = JSON.parse(readFileSync(file, "utf8")); } catch (error) { if (error instanceof SyntaxError) return { title: "", note: "" }; throw error; }
  return { title: typeof saved.title === "string" ? saved.title : "", note: typeof saved.note === "string" ? saved.note : "" };
}

function text(value: unknown, label: string, limit: number): string {
  if (typeof value !== "string") throw new TypeError(`A ${label} must be text.`);
  const trimmed = value.trim();
  if (trimmed.length > limit) throw new TypeError(`Keep the ${label} under ${limit} characters.`);
  return trimmed;
}

// Changes the fields given; an empty value clears that field, and the file goes once both are empty.
export function saveProjectInfo(root: string, name: string, change: Partial<Record<keyof ProjectInfo, unknown>>): ProjectInfo {
  const info = readProjectInfo(root, name);
  if ("title" in change) {
    const title = text(change.title, "display name", TITLE_LIMIT);
    if (/[\r\n]/.test(title)) throw new TypeError("Keep the display name on one line.");
    info.title = title === name ? "" : title;
  }
  if ("note" in change) info.note = text(change.note, "note", NOTE_LIMIT);
  const file = inside(casesetDir(root, name), INFO_FILE);
  const saved = Object.fromEntries(Object.entries(info).filter(([, value]) => value));
  if (Object.keys(saved).length) writeFileSync(file, `${JSON.stringify(saved, null, 2)}\n`);
  else rmSync(file, { force: true });
  return info;
}

// Display names for the project pickers; projects without one show their folder name.
export function projectTitles(root: string, names: string[]): Record<string, string> {
  return Object.fromEntries(names.flatMap((name) => { const { title } = readProjectInfo(root, name); return title ? [[name, title]] : []; }));
}

// Why a project cannot be deleted, or null when it can.
export function deletionBlock(root: string, name: string): string | null {
  if (name === "demo") return "The bundled demo cannot be deleted.";
  if (isTutorialProject(name)) return "The tutorial project cannot be deleted.";
  if (readPipelineRecord<PipelineRunRecord>(casesetDir(root, name), "latest.json")?.status === "running") return "Finish or stop the running pipeline first.";
  return null;
}

export function projectRows(root: string, names: string[]): ProjectRow[] {
  return names.map((name) => ({
    name,
    mode: name === "demo" || isTutorialProject(name) ? "local" as const : readProjectMode(root, name),
    updatedAt: benchmarkUpdatedAt(root, name),
    ...readProjectInfo(root, name),
    locked: deletionBlock(root, name),
  })).sort((a, b) => (b.updatedAt ?? "").localeCompare(a.updatedAt ?? "") || a.name.localeCompare(b.name));
}

// Moves a local project out of the list, keeping every file, and returns where it went (relative to the projects
// folder). Moving the folder back restores it.
export function archiveProject(root: string, name: string, now = new Date()): string {
  const source = casesetDir(root, name);
  const stamp = now.toISOString().replace(/[:.]/g, "-");
  const target = path.join(root, DELETED_FOLDER, `${name}-${stamp}`);
  mkdirSync(path.dirname(target), { recursive: true });
  if (existsSync(target)) throw new Error(`${path.relative(root, target)} already exists.`);
  renameSync(source, target);
  return path.relative(root, target);
}

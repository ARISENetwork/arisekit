import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import { casesetDir, inside } from "@/lib/caseset/paths";
import { projectMode, type ProjectExecutionMode } from "@/lib/project-mode";

function projectProvenance(file: string, name: string): Record<string, unknown> {
  if (!existsSync(file)) return { caseset_name: name };
  const value: unknown = JSON.parse(readFileSync(file, "utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError("Project provenance must be a JSON object.");
  return value as Record<string, unknown>;
}

export function readProjectMode(root: string, name: string): ProjectExecutionMode {
  const folder = casesetDir(root, name);
  return projectMode(projectProvenance(inside(folder, "provenance.json"), name).execution_mode);
}

export function saveProjectMode(root: string, name: string, value: unknown): boolean {
  const mode = projectMode(value);
  const folder = casesetDir(root, name);
  const file = inside(folder, "provenance.json");
  const provenance = projectProvenance(file, name);
  if (provenance.execution_mode === mode) return false;
  const temporary = inside(folder, `.provenance-${randomUUID()}.tmp`);
  writeFileSync(temporary, `${JSON.stringify({ ...provenance, execution_mode: mode, updated_at: new Date().toISOString() }, null, 2)}\n`, { flag: "wx", mode: existsSync(file) ? statSync(file).mode & 0o777 : 0o600 });
  renameSync(temporary, file);
  return true;
}

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { inside } from "@/lib/caseset/paths";
import { projectMode, type ProjectExecutionMode } from "@/lib/project-mode";
import { TEXT_V2_PIPELINE_V2_COMMIT } from "@/lib/text-v2-runtime";

export function createProject(root: string, name: string, idea: string, executionMode: ProjectExecutionMode = "api"): void {
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(name)) throw new TypeError("Project name must be 1-64 lowercase letters, digits, or hyphens.");
  if (idea.length > 6000) throw new TypeError("Benchmark idea must be at most 6000 characters.");
  const mode = projectMode(executionMode);
  mkdirSync(root, { recursive: true });
  const folder = inside(root, name);
  mkdirSync(folder);
  mkdirSync(path.join(folder, "cases"));
  writeFileSync(path.join(folder, "items.jsonl"), "", { flag: "wx" });
  const now = new Date().toISOString();
  writeFileSync(path.join(folder, "provenance.json"), `${JSON.stringify({ caseset_name: name, cases: [], trials: 1, execution_mode: mode, judge_scoring_source_commit: TEXT_V2_PIPELINE_V2_COMMIT, created_at: now, updated_at: now, ...(idea ? { description: idea } : {}) }, null, 2)}\n`, { flag: "wx" });
}

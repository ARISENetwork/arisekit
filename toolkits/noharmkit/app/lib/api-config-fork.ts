import { lstatSync, readFileSync, readdirSync, writeFileSync, type Stats } from "node:fs";
import path from "node:path";
import { casesetDir, inside } from "./caseset/paths";
import { exportableProjectPath } from "./project-export";
import { createProject } from "./project-create";
import { parseApiPipelineConfig, type ApiPipelineConfig } from "./api-pipeline-config";
import { saveApiPipelineConfig } from "./api-pipeline-store";
import type { ProjectFiles } from "./project-files";
import { materializeProject } from "./pipeline-workspace";

export function forkApiRun(root: string, source: string, name: string, raw: unknown): ApiPipelineConfig {
  if ([root, source, name].some(value => /holdout/i.test(value))) throw new TypeError("This source project path cannot be copied into a new run.");
  const folder = casesetDir(root, source);
  const config = parseApiPipelineConfig(raw);
  const provenance = JSON.parse(readFileSync(inside(folder, "provenance.json"), "utf8")) as Record<string, unknown>;
  const files: ProjectFiles = {};
  const read = (relative: string): void => {
    if (!exportableProjectPath(relative)) return;
    const file = path.join(folder, relative);
    const stat = sourceStat(file);
    if (!stat) return;
    if (stat.isSymbolicLink()) throw new TypeError("Linked source files cannot be copied into a new run.");
    if (stat.isDirectory()) for (const entry of readdirSync(file)) read(`${relative}/${entry}`);
    else if (stat.isFile()) files[relative] = readFileSync(inside(folder, ...relative.split("/"))).toString("base64");
    else throw new TypeError("Only ordinary source files can be copied into a new run.");
  };
  for (const relative of ["items.jsonl", "cases", "imports", "answer-tables", "drafts/dataset.json", "prompts.json"]) read(relative);
  createProject(root, name, "", "api");
  const target = casesetDir(root, name);
  materializeProject(target, files);
  const { inference: _inference, models: _models, model_labels: _modelLabels, ...sourceProvenance } = provenance;
  const now = new Date().toISOString();
  writeFileSync(inside(target, "provenance.json"), `${JSON.stringify({ ...sourceProvenance, caseset_name: name, execution_mode: "api", created_at: now, updated_at: now, forked_from: { project: source, created_at: now, purpose: "New collection run; copied source inputs and existing rubrics. No new clinical review or approval." } }, null, 2)}\n`, { mode: 0o600 });
  return saveApiPipelineConfig(root, name, config);
}

function sourceStat(file: string): Stats | null {
  try { return lstatSync(file); } catch (caught) { if ((caught as NodeJS.ErrnoException).code === "ENOENT") return null; throw caught; }
}

import { execFile } from "node:child_process";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { KIT_ROOT } from "./caseset/paths";
import { materializeProject, type PipelineWorkspace } from "./pipeline-workspace";
import { filesIn } from "./project-files";
import type { ProjectFiles } from "./project-files";
import type { ApiPipelineAction } from "./api-pipeline-action";
import type { ApiPipelineConfig } from "./api-pipeline-config";
import { preparePipelineDataset } from "./pipeline-dataset";

export interface PipelineInspection {
  status: "ready" | "blocked";
  operationIdentity?: string;
  reusableCalls: number;
  pending?: boolean;
  reason?: string;
}

export function pipelineRequest(workspace: Pick<PipelineWorkspace, "root" | "project" | "directory">, action: ApiPipelineAction, config: ApiPipelineConfig): Record<string, unknown> {
  const imports = preparePipelineDataset(workspace.root, workspace.project, action);
  const requested = { stage: action.stage, ...(action.rubricFormat ? { rubricFormat: action.rubricFormat } : {}), ...(imports.length ? { caseIds: imports.map(record => record.id) } : action.caseIds ? { caseIds: action.caseIds } : {}), ...(action.rubric ? { rubric: action.rubric } : {}), ...(action.prompt ? { prompt: action.prompt } : {}), ...(action.replaceOutdated ? { replaceOutdated: true } : {}), ...(action.allowPartial ? { allowPartial: true } : {}) };
  return { project: workspace.directory, action: requested, ...(action.allowPartial ? {} : { config }), ...(imports.length ? { importCases: imports } : {}) };
}

export async function inspectPipelineFiles(files: ProjectFiles, project: string, action: ApiPipelineAction, config: ApiPipelineConfig, python: string): Promise<PipelineInspection> {
  if (Object.keys(files).some(name => name.toLowerCase().includes("holdout"))) throw new Error("The project contains an excluded path.");
  const root = mkdtempSync(path.join(os.tmpdir(), "arisekit-inspect-"));
  const directory = path.join(root, project);
  materializeProject(directory, files);
  const request = pipelineRequest({ root, project, directory }, action, config);
  return new Promise((resolve, reject) => {
    const child = execFile(python, ["-u", path.join(KIT_ROOT, "tools/inspect_web_pipeline.py")], {
      cwd: KIT_ROOT, encoding: "utf8", maxBuffer: 2 * 1024 * 1024,
      env: { NODE_ENV: process.env.NODE_ENV, PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, PYTHONUNBUFFERED: "1" },
    }, (error, stdout, stderr) => {
      try {
        const result = JSON.parse(stdout) as PipelineInspection;
        if (result.status !== "ready" && result.status !== "blocked") throw new Error("The pipeline inspector returned an invalid status.");
        resolve(result);
      } catch (failure) { reject(error ? new Error(stderr.trim() || error.message) : failure); }
    });
    child.stdin?.end(`${JSON.stringify(request)}\n`);
  });
}

export function inspectPipeline(workspace: PipelineWorkspace, action: ApiPipelineAction, config: ApiPipelineConfig, python: string): Promise<PipelineInspection> {
  return inspectPipelineFiles(filesIn(workspace.directory), workspace.project, action, config, python);
}

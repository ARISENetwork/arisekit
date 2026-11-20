import { apiConfigImpact, ApiConfigImpactError } from "./api-config-impact";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { casesetDir, inside } from "@/lib/caseset/paths";
import { readProjectMode } from "@/lib/project-mode-store";
import { parseApiPipelineConfig, type ApiPipelineConfig, type ApiModelOption } from "@/lib/api-pipeline-config";
import type { ApiPipelineAction } from "@/lib/api-pipeline-action";
import { createApiPipelineConfig, initialModelTeams, type ApiModelStage } from "@/lib/api-model-teams";
import { isTutorialProject } from "@/lib/onboarding";

export function loadApiPipelineConfig(root: string, project: string): ApiPipelineConfig | null {
  const file = inside(casesetDir(root, project), "api-pipeline.json");
  return existsSync(file) ? parseApiPipelineConfig(JSON.parse(readFileSync(file, "utf8"))) : null;
}

export function validateApiModels(config: ApiPipelineConfig, models: ApiModelOption[], stage?: ApiPipelineAction["stage"]): void {
  const available = new Map(models.map(model => [model.id, model]));
  const teams = initialModelTeams(config);
  const stages: ApiModelStage[] = stage === "generate" ? ["generation", "rating"] : stage === "responses" ? ["responses"] : stage === "judge" ? ["judge"] : stage === "score" ? [] : ["generation", "rating", "responses", "judge"];
  const selected = stages.flatMap(name => [...teams[name].models, ...(teams[name].models.length > 1 && teams[name].integrator ? [teams[name].integrator] : [])]);
  const missing = [...new Set(selected)].filter(model => !available.has(model));
  if (missing.length) throw new TypeError(`These models are no longer in the OpenRouter catalog: ${missing.join(", ")}. Choose available models before running.`);
  for (const name of stages) {
    const team = teams[name];
    const roles = [
      { label: "contributor", ids: team.models, choices: team.modelReasoning },
      { label: "integrator", ids: team.models.length > 1 && team.integrator ? [team.integrator] : [], choices: team.integratorReasoning },
    ];
    for (const role of roles) for (const id of role.ids) {
      const effort = role.choices?.[id];
      if (effort !== undefined && !available.get(id)!.reasoning?.efforts.includes(effort)) throw new TypeError(`${name} ${role.label} ${id} does not list support for reasoning effort ${effort} in the current OpenRouter catalog.`);
    }
  }
}

export function saveApiPipelineConfig(root: string, project: string, raw: unknown): ApiPipelineConfig {
  if (readProjectMode(root, project) !== "api") throw new TypeError("Switch the project to API Mode before configuring API models.");
  const folder = casesetDir(root, project);
  const provenancePath = inside(folder, "provenance.json");
  const provenance = existsSync(provenancePath) ? JSON.parse(readFileSync(provenancePath, "utf8")) as { synthetic?: boolean } : {};
  if (isTutorialProject(project) || project === "demo" && provenance.synthetic === true) throw new TypeError("The prepared demo is read-only. Create your own project before configuring API models.");
  const config = parseApiPipelineConfig(raw);
  const impact = apiConfigImpact(root, project, config, loadApiPipelineConfig(root, project));
  if (impact) throw new ApiConfigImpactError(impact);
  const temporary = inside(folder, `.api-pipeline-${randomUUID()}.tmp`);
  writeFileSync(temporary, `${JSON.stringify(config, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, inside(folder, "api-pipeline.json"));
  return config;
}

export function addResponsePrompt(root: string, project: string, config: ApiPipelineConfig, id: string): ApiPipelineConfig {
  const teams = initialModelTeams(config);
  if (teams.responses.prompts?.includes(id)) return config;
  teams.responses.prompts = [...teams.responses.prompts ?? [], id];
  return saveApiPipelineConfig(root, project, createApiPipelineConfig(teams));
}

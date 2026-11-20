import type { ModelReasoning } from "./api-model-reasoning";
import { REASONING_EFFORTS, type ReasoningEffort } from "./api-model-reasoning";
import type { ApiModelStage, ApiModelTeam, ApiModelTeams } from "./api-model-teams";

export interface ApiPipelineConfigV1 {
  version: 1;
  generationModel: string;
  ratingModels: string[];
  responseModels: string[];
  judgeModel: string;
}

export interface ApiPipelineConfigV2 { version: 2; teams: ApiModelTeams }
export type ApiPipelineConfig = ApiPipelineConfigV1 | ApiPipelineConfigV2;

export interface ApiModelOption {
  id: string;
  name: string;
  contextLength: number;
  inputPrice: string | null;
  outputPrice: string | null;
  structured: boolean;
  reasoning?: ModelReasoning;
}

export function emptyApiPipelineConfig(): ApiPipelineConfigV1 {
  return { version: 1, generationModel: "", ratingModels: [], responseModels: [], judgeModel: "" };
}

const TEAM_LABELS: Record<ApiModelStage, string> = { generation: "Rubric generation", rating: "Harm rating", responses: "Models under test", judge: "Autograding" };

function modelId(raw: unknown, label: string): string {
  if (typeof raw !== "string" || !/^[a-z0-9][a-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._:+-]*$/.test(raw)
    || /^(api|local|subscription|codex|claude|direct)\//.test(raw)) {
    throw new TypeError(`${label} must use an OpenRouter provider/model ID.`);
  }
  return raw;
}

function modelList(raw: unknown, label: string, required: boolean): string[] {
  if (!Array.isArray(raw)) throw new TypeError(`${label} must be a list of model IDs.`);
  const values = raw.map(value => modelId(value, label));
  if (required && !values.length) throw new TypeError(label === "Models under test" ? "Choose at least one model under test." : `Choose at least one model for ${label.toLowerCase()}.`);
  if (new Set(values).size !== values.length) throw new TypeError(`${label} contains a duplicate model.`);
  return values;
}

function reasoningChoices(raw: unknown, active: string[], label: string): Record<string, ReasoningEffort> | undefined {
  if (raw === undefined) return undefined;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new TypeError(`${label} reasoning must map model IDs to effort levels.`);
  const choices: Record<string, ReasoningEffort> = {};
  for (const [id, effort] of Object.entries(raw)) {
    modelId(id, label);
    if (!active.includes(id)) throw new TypeError(`${label} reasoning includes an inactive model: ${id}.`);
    if (typeof effort !== "string" || !REASONING_EFFORTS.some(value => value === effort)) throw new TypeError(`${label} reasoning has an unsupported effort for ${id}.`);
    choices[id] = effort as ReasoningEffort;
  }
  return Object.keys(choices).length ? choices : undefined;
}

function promptList(raw: unknown): string[] | undefined {
  if (raw === undefined) return undefined;
  if (!Array.isArray(raw)) throw new TypeError("Response prompts must be a list of prompt IDs.");
  for (const id of raw) if (typeof id !== "string" || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(id)) throw new TypeError("Response prompts must use saved prompt IDs.");
  if (new Set(raw).size !== raw.length) throw new TypeError("Response prompts contain a duplicate prompt.");
  return raw.length ? raw as string[] : undefined;
}

function modelTeam(raw: unknown, stage: ApiModelStage): ApiModelTeam {
  const label = TEAM_LABELS[stage];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new TypeError(`Provide the ${label.toLowerCase()} model team.`);
  const team = raw as Record<string, unknown>;
  const models = modelList(team.models, label, stage !== "rating");
  const integrates = stage !== "responses" && models.length > 1;
  if (integrates && !team.integrator) throw new TypeError(`Choose an integrator for ${label.toLowerCase()} when selecting multiple models.`);
  const integrator = integrates ? modelId(team.integrator, `${label} integrator`) : "";
  const modelReasoning = reasoningChoices(team.modelReasoning, models, `${label} contributor`);
  const integratorReasoning = integrator ? reasoningChoices(team.integratorReasoning, [integrator], `${label} integrator`) : undefined;
  const prompts = stage === "responses" ? promptList(team.prompts) : undefined;
  return { models, integrator, ...(modelReasoning ? { modelReasoning } : {}), ...(integratorReasoning ? { integratorReasoning } : {}), ...(prompts ? { prompts } : {}) };
}

export function parseApiPipelineConfig(raw: ApiPipelineConfigV1): ApiPipelineConfigV1;
export function parseApiPipelineConfig(raw: ApiPipelineConfigV2): ApiPipelineConfigV2;
export function parseApiPipelineConfig(raw: unknown): ApiPipelineConfig;
export function parseApiPipelineConfig(raw: unknown): ApiPipelineConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new TypeError("Provide the API model setup.");
  const config = raw as Record<string, unknown>;
  if (config.version === 2) {
    if (!config.teams || typeof config.teams !== "object" || Array.isArray(config.teams)) throw new TypeError("Provide the API model teams.");
    const teams = config.teams as Record<string, unknown>;
    return { version: 2, teams: {
      generation: modelTeam(teams.generation, "generation"),
      rating: modelTeam(teams.rating, "rating"),
      responses: modelTeam(teams.responses, "responses"),
      judge: modelTeam(teams.judge, "judge"),
    } };
  }
  if (config.version !== 1) throw new TypeError("Unsupported API model setup version.");
  return {
    version: 1,
    generationModel: modelId(config.generationModel, "Rubric generation"),
    ratingModels: modelList(config.ratingModels, "Harm rating", false),
    responseModels: modelList(config.responseModels, "Models under test", true),
    judgeModel: modelId(config.judgeModel, "Autograding"),
  };
}

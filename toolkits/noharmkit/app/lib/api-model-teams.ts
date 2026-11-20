import { parseApiPipelineConfig, type ApiPipelineConfig, type ApiPipelineConfigV2 } from "./api-pipeline-config";
import type { ReasoningEffort } from "./api-model-reasoning";
import { DEFAULT_JUDGE } from "./pipeline-defaults";

export interface ApiModelTeam { models: string[]; integrator: string; modelReasoning?: Record<string, ReasoningEffort>; integratorReasoning?: Record<string, ReasoningEffort>; prompts?: string[] }
export type ApiModelStage = "generation" | "rating" | "responses" | "judge";
export type ApiModelTeams = Record<ApiModelStage, ApiModelTeam>;

// A new setup starts from the default judge and its reasoning effort.
function defaultJudgeTeam(): ApiModelTeam {
  return { models: [DEFAULT_JUDGE.model], integrator: "", ...(DEFAULT_JUDGE.reasoning ? { modelReasoning: { [DEFAULT_JUDGE.model]: DEFAULT_JUDGE.reasoning } } : {}) };
}

export function initialModelTeams(config?: ApiPipelineConfig | null): ApiModelTeams {
  if (config?.version === 2) return Object.fromEntries(Object.entries(config.teams).map(([stage, team]) => [stage, {
    models: [...team.models], integrator: stage === "responses" ? "" : team.integrator,
    ...(team.modelReasoning ? { modelReasoning: { ...team.modelReasoning } } : {}),
    ...(stage !== "responses" && team.integratorReasoning ? { integratorReasoning: { ...team.integratorReasoning } } : {}),
    ...(stage === "responses" && team.prompts?.length ? { prompts: [...team.prompts] } : {}),
  }])) as ApiModelTeams;
  return {
    generation: { models: config?.generationModel ? [config.generationModel] : [], integrator: "" },
    rating: { models: [...config?.ratingModels ?? []], integrator: "" },
    responses: { models: [...config?.responseModels ?? []], integrator: "" },
    judge: config ? { models: config.judgeModel ? [config.judgeModel] : [], integrator: "" } : defaultJudgeTeam(),
  };
}

export function createApiPipelineConfig(teams: ApiModelTeams): ApiPipelineConfigV2 {
  const activeTeam = (team: ApiModelTeam): ApiModelTeam => {
    const integrator = team.models.length > 1 ? team.integrator : "";
    const modelReasoning = Object.fromEntries(Object.entries(team.modelReasoning ?? {}).filter(([id]) => team.models.includes(id)));
    const integratorReasoning = Object.fromEntries(Object.entries(team.integratorReasoning ?? {}).filter(([id]) => integrator && id === integrator));
    return { models: [...team.models], integrator, ...(Object.keys(modelReasoning).length ? { modelReasoning } : {}), ...(Object.keys(integratorReasoning).length ? { integratorReasoning } : {}), ...(team.prompts?.length ? { prompts: [...team.prompts] } : {}) };
  };
  return parseApiPipelineConfig({ version: 2, teams: {
    generation: activeTeam(teams.generation), rating: activeTeam(teams.rating), responses: activeTeam(teams.responses), judge: activeTeam(teams.judge),
  } });
}

export function toggleTeamModel(team: ApiModelTeam, id: string): ApiModelTeam {
  return { ...team, models: team.models.includes(id) ? team.models.filter(model => model !== id) : [...team.models, id] };
}

export function setTeamReasoning(team: ApiModelTeam, role: "modelReasoning" | "integratorReasoning", id: string, effort: ReasoningEffort | ""): ApiModelTeam {
  const choices = { ...team[role] };
  if (effort) choices[id] = effort;
  else delete choices[id];
  return { ...team, [role]: choices };
}

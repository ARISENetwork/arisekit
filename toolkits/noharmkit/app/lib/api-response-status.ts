import type { ReasoningEffort } from "./api-model-reasoning";
import type { ApiModelTeam } from "./api-model-teams";
import type { Benchmark } from "./caseset/metrics";
import type { CasePage, ResponseRoute } from "./caseset/types";
import { apiResponseRoute, responseModelIdentity, responseSettingsDifference } from "./response-settings";
import { expectedTrial, projectTrials, trialNumbers } from "./caseset/trials";

export interface PromptName { id: string; name: string }

export interface ApiResponseRow {
  id: string;
  model: string;
  status: "Pending" | "Complete" | "Failed" | "Different settings";
  completed: number;
  failed: number;
  pending: number;
  total: number;
  reasoning?: ReasoningEffort;
  prompt?: string;
  modelId?: string;
  mismatch?: string;
}

const slotIdentity = (model: string, item: string, trial: number): string => JSON.stringify([model, item, trial]);

function declaredRoute(page: CasePage, id: string): ResponseRoute | undefined {
  const inference = page.provenance.inference as { binding_version?: number; model_routes?: Record<string, ResponseRoute> } | undefined;
  return inference?.binding_version === 2 ? inference.model_routes?.[id] : undefined;
}

function promptName(page: CasePage, setId: string, promptId: string, prompts: PromptName[]): string {
  const inference = page.provenance.inference as { set_prompts?: Record<string, { name?: string }> } | undefined;
  return prompts.find(prompt => prompt.id === promptId)?.name ?? inference?.set_prompts?.[setId]?.name ?? promptId;
}

function settingsMismatch(route: ResponseRoute | undefined, id: string, reasoning: ReasoningEffort | undefined): string | null {
  if (!route) return null;
  const difference = responseSettingsDifference(route, apiResponseRoute(id, reasoning), "reasoning");
  if (difference === "route") return `Stored response route ${route.backend}/${route.model} differs from the current OpenRouter model ${id}. Use a new project/run to change collection settings.`;
  const stored = route.kwargs.reasoning_effort ?? undefined;
  return difference ? `Stored response reasoning is ${stored ?? "Model default"}; current setup uses ${reasoning ?? "Model default"}. Use a new project/run to change collection settings.` : null;
}

export function apiResponseRows(bench: Benchmark, team: ApiModelTeam, prompts: PromptName[] = []): ApiResponseRow[] {
  const trials = projectTrials(bench.trials);
  const total = bench.cases.reduce((sum, c) => sum + c.items.length * trials, 0);
  const sets = team.models.flatMap(modelId => [{ modelId, promptId: null }, ...(team.prompts ?? []).map(promptId => ({ modelId, promptId }))]);
  return sets.map(({ modelId, promptId }) => {
    const id = promptId ? `${modelId}+${promptId}` : modelId;
    const model = responseModelIdentity(id);
    let completed = 0;
    let failed = 0;
    const reasoning = team.modelReasoning?.[modelId];
    const mismatches = new Set<string>();
    for (const c of bench.cases) {
      const items = new Set(c.items);
      const declared = declaredRoute(c.page, id);
      for (const { row } of c.responses) {
        if (row.model !== model || !items.has(row.itemId) || !expectedTrial(row.trial, trials)) continue;
        const mismatch = settingsMismatch(row.route ?? declared, modelId, reasoning);
        if (mismatch) mismatches.add(mismatch);
        if (row.responseError) failed += 1;
        else if (mismatch) continue;
        else if (row.response?.trim()) completed += 1;
      }
    }
    const named = promptId ? promptName(bench.cases[0]?.page ?? ({ provenance: {} } as CasePage), id, promptId, prompts) : null;
    return {
      id, model, completed, failed, pending: total - completed - failed, total,
      status: mismatches.size ? "Different settings" : failed ? "Failed" : total > 0 && completed === total ? "Complete" : "Pending",
      ...(reasoning ? { reasoning } : {}),
      ...(named ? { prompt: named, modelId } : {}),
      ...(mismatches.size ? { mismatch: [...mismatches].join(" ") } : {}),
    };
  });
}

export function withApiResponseModels(bench: Benchmark, team: ApiModelTeam): Benchmark {
  const rows = apiResponseRows(bench, team);
  const trials = trialNumbers(projectTrials(bench.trials));
  const configured = rows.map(row => row.model);
  const completed = rows.reduce((sum, row) => sum + row.completed, 0);
  const failed = rows.reduce((sum, row) => sum + row.failed, 0);
  return {
    ...bench,
    models: [...new Set([...bench.models, ...configured])],
    cases: bench.cases.map(c => {
      const missing = [...c.missing];
      const seen = new Set([
        ...c.responses.map(({ row }) => slotIdentity(row.model, row.itemId, row.trial)),
        ...missing.map(row => slotIdentity(row.model, row.itemId, row.trial)),
      ]);
      for (const model of configured) for (const itemId of c.items) for (const trial of trials) {
        const identity = slotIdentity(model, itemId, trial);
        if (!seen.has(identity)) {
          missing.push({ caseId: c.caseId, itemId, model, trial });
          seen.add(identity);
        }
      }
      return { ...c, missing };
    }),
    steps: {
      ...bench.steps,
      responses: {
        ...bench.steps.responses,
        done: completed, total: rows.reduce((sum, row) => sum + row.total, 0), failed,
        dot: failed ? "bad" : completed ? "model" : "none",
      },
    },
  };
}

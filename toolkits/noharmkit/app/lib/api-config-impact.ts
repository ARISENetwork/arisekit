import { readFileSync } from "node:fs";
import { casesetDir, inside, list } from "./caseset/paths";
import { initialModelTeams } from "./api-model-teams";
import type { ApiPipelineConfig } from "./api-pipeline-config";
import type { ResponseRoute } from "./caseset/types";
import { apiResponseRoute, responseModelIdentity, responseSettingsDifference } from "./response-settings";

export interface ApiConfigImpact {
  code: "new_run_required";
  reasons: string[];
  records: number;
}

export function apiConfigImpact(root: string, project: string, config: ApiPipelineConfig, previous: ApiPipelineConfig | null): ApiConfigImpact | null {
  const folder = casesetDir(root, project);
  const provenance = JSON.parse(readFileSync(inside(folder, "provenance.json"), "utf8")) as { models?: string[]; inference?: { model_routes?: Record<string, ResponseRoute> } };
  const routes = provenance.inference?.model_routes ?? {};
  const receipts = list(folder, "results", "responses").filter(name => name.endsWith(".jsonl")).flatMap(name =>
    readFileSync(inside(folder, "results", "responses", name), "utf8").split("\n").filter(line => line.trim()).map(line => ({ model: name.slice(0, -6), row: JSON.parse(line) as { route?: ResponseRoute } })));
  // Saved judgments carry call receipts bound to the setup format that made them; the newer team format cannot reuse
  // receipts from the earlier one, so judging would fail after collection had already spent credits.
  const judged = list(folder, "results", "judge").some(name => name.endsWith(".jsonl") && readFileSync(inside(folder, "results", "judge", name), "utf8").trim() !== "");
  const formatChange = previous?.version === 1 && config.version === 2 && judged;
  if (!receipts.length && !Object.keys(routes).length && !formatChange) return null;
  const team = initialModelTeams(config).responses;
  const before = previous ? initialModelTeams(previous).responses : null;
  const reasons = new Set<string>();
  if (formatChange) reasons.add("Saved autograding was made with the earlier model setup format. Changing the setup or adding a prompt needs a new run.");
  const setsOf = (id: string): string[] => [id, ...(team.prompts ?? []).map(prompt => `${id}+${prompt}`)];
  const setIds = team.models.flatMap(setsOf);
  const declared = [...new Set([...provenance.models ?? [], ...Object.keys(routes)])];
  const declaredModels = provenance.models?.length ? provenance.models.map(id => routes[id]?.model ?? id) : before?.models ?? [...Object.keys(routes).map(id => routes[id].model ?? id), ...receipts.map(receipt => receipt.row.route?.model ?? receipt.model)];
  if (declaredModels.length && JSON.stringify([...new Set(declaredModels.map(responseModelIdentity))].sort()) !== JSON.stringify(team.models.map(responseModelIdentity).sort())) reasons.add("The models under test have changed after collection started.");
  const scopeStems = new Set(setIds.map(responseModelIdentity));
  if (receipts.some(receipt => !scopeStems.has(receipt.model)) || declared.some(id => !setIds.includes(id))) reasons.add("The selected models and prompts would exclude retained collection records.");
  for (const id of team.models) {
    const desired = apiResponseRoute(id, team.modelReasoning?.[id]);
    for (const setId of setsOf(id)) {
      const stored = receipts.filter(receipt => receipt.model === responseModelIdentity(setId));
      if (routes[setId] && responseSettingsDifference(routes[setId], desired, "all") || stored.some(receipt => receipt.row.route && responseSettingsDifference(receipt.row.route, desired, "all"))) reasons.add(`${setId}: the saved collection route or reasoning differs from this setup.`);
      if (!routes[setId] && stored.some(receipt => !receipt.row.route)) reasons.add(`${setId}: older collection records do not identify an OpenRouter route. Keep them in the original run.`);
    }
    if (before?.models.includes(id) && responseSettingsDifference(apiResponseRoute(id, before.modelReasoning?.[id]), desired, "reasoning")) reasons.add(`${id}: reasoning changed after collection started.`);
  }
  return reasons.size ? { code: "new_run_required", reasons: [...reasons], records: receipts.length } : null;
}

export class ApiConfigImpactError extends Error {
  constructor(readonly impact: ApiConfigImpact) {
    super("These collection settings need a new run. The original setup and saved results have not changed.");
  }
}

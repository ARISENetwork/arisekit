import type { ReasoningEffort } from "./api-model-reasoning";
import type { ResponseRoute } from "./caseset/types";

export function responseModelIdentity(id: string): string {
  return id.replace(/[/:]/g, "-");
}

export function apiResponseRoute(id: string, reasoning?: ReasoningEffort): ResponseRoute {
  return { backend: "openrouter", model: id, kwargs: reasoning ? { reasoning_effort: reasoning } : {} };
}

export function responseSettingsDifference(actual: ResponseRoute, desired: ResponseRoute, parameters: "all" | "reasoning"): "route" | "parameters" | null {
  if (actual.backend !== desired.backend || actual.model !== desired.model) return "route";
  // Save guards bind every parameter; coverage retains legacy reasoning-only semantics.
  if (parameters === "reasoning") {
    const actualEffort = actual.kwargs.reasoning_effort ?? undefined;
    const desiredEffort = desired.kwargs.reasoning_effort ?? undefined;
    return actualEffort === desiredEffort ? null : "parameters";
  }
  const settings = (route: ResponseRoute): string => JSON.stringify(Object.entries(route.kwargs).sort());
  return settings(actual) === settings(desired) ? null : "parameters";
}

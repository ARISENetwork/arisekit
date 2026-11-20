import defaults from "../../pipeline/e2e/pipeline_v2_defaults.json";
import { REASONING_EFFORTS, type ReasoningEffort } from "./api-model-reasoning";

// Default model settings, shared with the command line (pipeline_v2_defaults.json) so both start from the same judge.
interface Route { backend: string; model: string; reasoning_effort?: string }

// The app calls every model through OpenRouter, so a route is named by its OpenRouter model ID.
export function openRouterId(route: Route): string {
  if (route.backend === "openrouter") return route.model;
  if (route.backend === "openai") return `openai/${route.model}`;
  throw new Error(`No OpenRouter model ID for the ${route.backend} route to ${route.model}.`);
}

function effort(route: Route): ReasoningEffort | undefined {
  const value = route.reasoning_effort;
  if (value === undefined) return undefined;
  if (!(REASONING_EFFORTS as readonly string[]).includes(value)) throw new Error(`Unknown reasoning effort ${value} in the pipeline defaults.`);
  return value as ReasoningEffort;
}

export const DEFAULT_JUDGE = { model: openRouterId(defaults.judge), reasoning: effort(defaults.judge) };

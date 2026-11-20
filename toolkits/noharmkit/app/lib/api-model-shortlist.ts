import type { ApiModelOption } from "./api-pipeline-config";

// Editorial starting points checked against OpenRouter on 2026-10-25, not a pipeline performance ranking.
export const RECOMMENDED_MODEL_IDS = [
  "openai/gpt-6-astra", "openai/gpt-6.1-sol", "openai/gpt-6-luna",
  "anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5",
  "google/gemini-4-argon", "google/gemini-3.8-flash",
  "deepseek/deepseek-v4.1-flash-1017", "moonshotai/kimi-k3.1-pro",
  "qwen/qwen3.8-max-0902", "z-ai/glm-5.3-flash", "x-ai/grok-4.7",
  "meta/muse-spark-1.3", "mistralai/mistral-large-4-0",
] as const;

export function recommendedModels(models: ApiModelOption[]): ApiModelOption[] {
  const catalog = new Map(models.map(model => [model.id, model]));
  return RECOMMENDED_MODEL_IDS.flatMap(id => catalog.has(id) ? [catalog.get(id)!] : []);
}

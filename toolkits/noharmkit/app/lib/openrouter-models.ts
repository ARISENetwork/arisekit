import type { ApiModelOption } from "@/lib/api-pipeline-config";
import { parseModelReasoning } from "@/lib/api-model-reasoning";

export function parseOpenRouterModels(raw: unknown): ApiModelOption[] {
  const payload = raw as { data?: { id: string; name: string; context_length: number; architecture?: { output_modalities?: string[] }; supported_parameters?: string[]; reasoning?: unknown; pricing?: { prompt?: string; completion?: string } }[] };
  if (!Array.isArray(payload?.data)) throw new TypeError("OpenRouter returned an invalid model catalog.");
  return payload.data.filter(model => typeof model.id === "string" && typeof model.name === "string" && model.architecture?.output_modalities?.includes("text") && !model.id.startsWith("openrouter/")).map(model => {
    const reasoning = parseModelReasoning(model.reasoning);
    return {
      id: model.id, name: model.name, contextLength: model.context_length,
      inputPrice: model.pricing?.prompt ?? null, outputPrice: model.pricing?.completion ?? null,
      structured: model.supported_parameters?.includes("structured_outputs") ?? false,
      ...(reasoning ? { reasoning } : {}),
    };
  }).sort((a, b) => a.name.localeCompare(b.name));
}

export async function loadOpenRouterModels(fetcher: typeof fetch = fetch): Promise<ApiModelOption[]> {
  const response = await fetcher("https://openrouter.ai/api/v1/models", { cache: "no-store", signal: AbortSignal.timeout(15_000) });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message ?? `OpenRouter model catalog returned HTTP ${response.status}.`);
  return parseOpenRouterModels(payload);
}

import { sanitizeModel } from "./metrics";
import { modelName } from "@/lib/model-names";

const UNPROMPTED_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

interface SetPrompt { id?: string; name: string; sha256: string }
type Provenance = Record<string, unknown>;

function declaredSet(model: string, provenance: Provenance): string | undefined {
  const declared = Array.isArray(provenance.models) ? provenance.models.find((id) => typeof id === "string" && sanitizeModel(id) === model) : undefined;
  return declared as string | undefined;
}

function inferenceOf(provenance: Provenance): { set_prompts?: Record<string, SetPrompt>; template_sha256?: unknown } {
  return (provenance.inference && typeof provenance.inference === "object" ? provenance.inference : {}) as ReturnType<typeof inferenceOf>;
}

export function promptOf(model: string, provenance: Provenance): SetPrompt | "prompt file" | null {
  const inference = inferenceOf(provenance);
  const declared = declaredSet(model, provenance);
  const prompt = declared ? inference.set_prompts?.[declared] : Object.entries(inference.set_prompts ?? {}).find(([id]) => sanitizeModel(id) === model)?.[1];
  if (prompt) return { name: prompt.name, sha256: prompt.sha256 };
  const legacy = inference.template_sha256;
  return typeof legacy === "string" && legacy !== UNPROMPTED_SHA256 ? "prompt file" : null;
}

function baseModel(model: string, provenance: Provenance): string {
  const declared = declaredSet(model, provenance);
  if (!declared) return model;
  const id = inferenceOf(provenance).set_prompts?.[declared]?.id;
  return id && declared.endsWith(`+${id}`) ? declared.slice(0, -(id.length + 1)) : declared;
}

export function orderResponseSets(models: string[], provenance: Provenance): string[] {
  const groups = new Map<string, string[]>();
  for (const model of models) {
    const key = baseModel(model, provenance);
    groups.set(key, [...(groups.get(key) ?? []), model]);
  }
  const prompted = (model: string): number => {
    const found = promptOf(model, provenance);
    return typeof found === "object" && found ? 1 : 0;
  };
  return [...groups.values()].flatMap(group => [...group].sort((a, b) => prompted(a) - prompted(b)));
}

export function modelLabel(model: string, provenance: Provenance): string {
  const found = promptOf(model, provenance);
  const suffix = found === null ? "" : `, ${found === "prompt file" ? "prompt file" : found.name}`;
  return `${modelBaseLabel(model, provenance)}${suffix}`;
}

// The model's name without its prompt, for views that already show the prompt.
export function modelBaseLabel(model: string, provenance: Provenance): string {
  const labels = provenance.model_labels;
  if (labels && typeof labels === "object" && model in labels) {
    const label = (labels as Record<string, unknown>)[model];
    if (typeof label === "string") return label;
  }
  const base = baseModel(model, provenance);
  return modelName(base) ?? base.replace(/^[^/]+\//, "");
}

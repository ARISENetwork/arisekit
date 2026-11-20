// Display names for models the toolkit suggests or has run, by OpenRouter ID. Unlisted models show their ID.
export interface KnownModel { id: string; organization: string; name: string }

// The order of the first entries is the order the model checklist suggests them in.
export const SUGGESTED_MODELS: readonly KnownModel[] = [
  { organization: "OpenAI", name: "GPT-6 Astra", id: "openai/gpt-6-astra" },
  { organization: "OpenAI", name: "GPT-6.1 Sol", id: "openai/gpt-6.1-sol" },
  { organization: "Anthropic", name: "Claude Fable 5.1", id: "anthropic/claude-fable-5.1" },
  { organization: "Anthropic", name: "Claude Opus 5.5", id: "anthropic/claude-opus-5.5" },
  { organization: "Google", name: "Gemini 3.8 Flash", id: "google/gemini-3.8-flash" },
  { organization: "DeepSeek", name: "DeepSeek V4.1 Flash", id: "deepseek/deepseek-v4.1-flash" },
  { organization: "SpaceXAI", name: "Grok 4.6", id: "x-ai/grok-4.6" },
  { organization: "Meta", name: "Muse Spark 1.3", id: "meta/muse-spark-1.3" },
  { organization: "Moonshot AI", name: "Kimi K3", id: "moonshotai/kimi-k3" },
];

const KNOWN: readonly KnownModel[] = [
  ...SUGGESTED_MODELS,
  { organization: "OpenAI", name: "GPT-6 Luna", id: "openai/gpt-6-luna" },
  { organization: "Google", name: "Gemini 4 Argon", id: "google/gemini-4-argon" },
  { organization: "Anthropic", name: "Claude Sonnet 5.5", id: "anthropic/claude-sonnet-5.5" },
];

const ORGANIZATIONS: Readonly<Record<string, string>> = {
  openai: "OpenAI", anthropic: "Anthropic", google: "Google", deepseek: "DeepSeek", "x-ai": "SpaceXAI", meta: "Meta",
  moonshotai: "Moonshot AI", qwen: "Qwen", "z-ai": "Z.ai", mistralai: "Mistral AI",
};

// Accepts an OpenRouter ID or its file-safe form (slashes and colons as hyphens).
function known(id: string): KnownModel | undefined {
  return KNOWN.find((model) => model.id === id || model.id.replace(/[/:]/g, "-") === id);
}

export function modelName(id: string): string | null {
  return known(id)?.name ?? null;
}

export function modelOrganization(id: string): string | null {
  return known(id)?.organization ?? (id.includes("/") ? ORGANIZATIONS[id.split("/")[0]] ?? null : null);
}

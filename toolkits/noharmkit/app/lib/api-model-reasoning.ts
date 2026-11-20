export const REASONING_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"] as const;
export type ReasoningEffort = typeof REASONING_EFFORTS[number];
export interface ModelReasoning {
  efforts: ReasoningEffort[];
  mandatory: boolean;
  defaultEffort?: ReasoningEffort;
  defaultEnabled?: boolean;
}

export const REASONING_LABELS: Record<ReasoningEffort, string> = { none: "Off", minimal: "Minimal", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Maximum" };

export function parseModelReasoning(raw: unknown): ModelReasoning | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const info = raw as Record<string, unknown>;
  if (info.supported_efforts !== null && !Array.isArray(info.supported_efforts)) return undefined;
  const supported = info.supported_efforts === null ? REASONING_EFFORTS : info.supported_efforts as unknown[];
  const mandatory = info.mandatory === true;
  const efforts = REASONING_EFFORTS.filter(effort => supported.includes(effort) && !(mandatory && effort === "none"));
  if (!efforts.length) return undefined;
  const defaultEffort = REASONING_EFFORTS.find(effort => effort === info.default_effort);
  return { efforts, mandatory, ...(defaultEffort ? { defaultEffort } : {}), ...(typeof info.default_enabled === "boolean" ? { defaultEnabled: info.default_enabled } : {}) };
}

export function defaultReasoningLabel(info: ModelReasoning): string {
  if (info.defaultEnabled === false) return "Default (Off)";
  if ((info.mandatory || info.defaultEnabled) && info.defaultEffort) return `Default (${REASONING_LABELS[info.defaultEffort]})`;
  return "Model default";
}

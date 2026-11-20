export interface ExecutionAvailability { available: boolean; reason: string }
export interface ApiExecutionReadiness { modelCalls: ExecutionAvailability; scoring: ExecutionAvailability }

export function executionReadiness({ pythonError, hasApiKey }: { pythonError?: string; hasApiKey: boolean }): ApiExecutionReadiness {
  return {
    modelCalls: pythonError ? { available: false, reason: pythonError } : hasApiKey ? { available: true, reason: "API execution is ready. Model calls use OpenRouter credits." } : { available: false, reason: "API model calls are unavailable until the local server has OPENROUTER_API_KEY configured. You can still save your model setup." },
    scoring: pythonError ? { available: false, reason: pythonError } : { available: true, reason: "Local deterministic scoring is ready. No model calls or API credits are needed." },
  };
}

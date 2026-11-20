import { executionReadiness, type ApiExecutionReadiness } from "./api-execution-readiness";
import { pipelinePython } from "./pipeline-runner";
import { openRouterApiKey } from "./openrouter-key";

export function pipelineReadiness(): ApiExecutionReadiness {
  let pythonError: string | undefined;
  try { pipelinePython(); } catch (caught) { pythonError = (caught as Error).message; }
  return executionReadiness({ pythonError, hasApiKey: Boolean(openRouterApiKey()) });
}

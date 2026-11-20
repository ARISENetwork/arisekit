export interface ApiPipelineAction {
  stage: "generate" | "responses" | "judge" | "score";
  caseIds?: string[];
  rubric?: string;
  sourceId?: string;
  draftKey?: string;
  rubricFormat?: "text-v2" | "answer-table";
  prompt?: string;
  replaceOutdated?: true;
  allowPartial?: true;
}

export function generateRubricLabel(caseIds: string[] | undefined): string {
  return caseIds?.length === 1 ? "Generate Rubric" : "Generate Rubrics";
}

export function pipelineSourceId(value: string): string {
  const relative = value.slice(value.lastIndexOf("/imports/") + 1);
  const source = value.startsWith("imports/") ? value : relative;
  if (!/^imports\/[a-f0-9-]{36}\/[^/\\]+\.(csv|json)$/i.test(source) || source.split("/").some(part => part === "." || part === "..")) throw new TypeError("Choose a saved dataset upload from this project.");
  return source;
}

export function parseApiPipelineAction(raw: unknown): ApiPipelineAction {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new TypeError("Choose a pipeline action.");
  const action = raw as Record<string, unknown>;
  if (!["generate", "responses", "judge", "score"].includes(String(action.stage))) throw new TypeError("Unknown pipeline stage.");
  const parsed: ApiPipelineAction = { stage: action.stage as ApiPipelineAction["stage"] };
  if (action.stage === "generate") {
    if (action.rubricFormat !== undefined && action.rubricFormat !== "text-v2" && action.rubricFormat !== "answer-table") throw new TypeError("Choose a supported rubric format.");
    parsed.rubricFormat = action.rubricFormat === "answer-table" ? "answer-table" : "text-v2";
  } else if (action.rubricFormat !== undefined) throw new TypeError("Rubric format belongs to generation; judging and scoring follow the saved rubric.");
  if (action.caseIds !== undefined) {
    if (!Array.isArray(action.caseIds) || !action.caseIds.length || !action.caseIds.every(id => typeof id === "string" && /^[A-Za-z0-9_]+$/.test(id)) || new Set(action.caseIds).size !== action.caseIds.length) throw new TypeError("Choose valid, distinct case IDs.");
    if (action.stage !== "generate" && action.stage !== "judge") throw new TypeError("Case selection belongs to rubric generation or autograding.");
    parsed.caseIds = action.caseIds;
  }
  if (action.rubric !== undefined) {
    if (typeof action.rubric !== "string" || !/^(run[1-9]\d*|reviewed-[a-z0-9][a-z0-9-]{1,31})$/.test(action.rubric)) throw new TypeError("Choose a saved rubric version.");
    parsed.rubric = action.rubric;
  }
  if (action.sourceId !== undefined) {
    if (action.stage !== "generate" || typeof action.sourceId !== "string") throw new TypeError("Dataset imports belong to rubric generation.");
    parsed.sourceId = pipelineSourceId(action.sourceId);
    if (parsed.sourceId !== action.sourceId) throw new TypeError("Use a project-relative upload identity.");
  }
  if (action.draftKey !== undefined) {
    if (action.stage !== "generate" || typeof action.draftKey !== "string" || !action.draftKey || action.draftKey.length > 128 || action.draftKey.includes("/") || action.draftKey.includes("\\")) throw new TypeError("Choose a saved dataset draft.");
    parsed.draftKey = action.draftKey;
  }
  if (action.prompt !== undefined) {
    if (action.stage !== "responses") throw new TypeError("A prompt belongs to response collection.");
    if (typeof action.prompt !== "string" || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(action.prompt)) throw new TypeError("Choose a saved prompt.");
    parsed.prompt = action.prompt;
  }
  if (action.replaceOutdated !== undefined) {
    if ((action.stage !== "responses" && action.stage !== "judge") || action.replaceOutdated !== true) throw new TypeError("Replacing out-of-date results belongs to response collection or autograding.");
    parsed.replaceOutdated = true;
  }
  if (action.allowPartial !== undefined) {
    if (action.stage !== "score" || action.allowPartial !== true) throw new TypeError("Partial scoring belongs to scoring.");
    parsed.allowPartial = true;
  }
  if (parsed.sourceId && parsed.draftKey) throw new TypeError("Choose one dataset source.");
  return parsed;
}

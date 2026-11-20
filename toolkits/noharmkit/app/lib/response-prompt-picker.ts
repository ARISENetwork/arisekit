import type { ApiPipelineAction } from "@/lib/api-pipeline-action";

export interface ChosenPrompt { id: string; name: string; text: string }

// Collection without a prompt still reads prompts.json once any saved prompt is listed or recorded.
export function brokenPromptsNote(inUse?: boolean): string {
  if (inUse === true) return "Collection without a prompt is blocked too, because this project already uses saved prompts.";
  if (inUse === false) return "Collection without a prompt still works.";
  return "Collection without a prompt still works only if no saved prompt is in use.";
}

// Responses collected for an earlier Task. Collection moves them aside (with their autograding and scores) only on confirmation.
export interface OutdatedResponses { count: number; cases: string[] }
export const NO_OUTDATED: OutdatedResponses = { count: 0, cases: [] };

export function outdatedResponses(cases: { caseId: string; responses: { row: { outdated?: string } }[] }[]): OutdatedResponses {
  const hits = cases.flatMap((c) => c.responses.filter((r) => r.row.outdated === "task").map(() => c.caseId));
  return { count: hits.length, cases: [...new Set(hits)] };
}

export const collectLabel = (outdated: OutdatedResponses): string => outdated.count ? "Replace and collect" : "Collect Responses";

// Autograding made against a rubric an edit to the case text put out of date. Autograding moves it aside on confirmation.
export function staleAutograding(cases: { caseId: string; page: { tables: { version: string; outdated?: string }[] }; responses: { row: { record?: { rubric?: string } | null } }[] }[]): OutdatedResponses {
  const hits = cases.flatMap((c) => {
    const outdated = new Set(c.page.tables.filter((t) => t.outdated).map((t) => t.version));
    return c.responses.filter((r) => r.row.record?.rubric && outdated.has(r.row.record.rubric)).map(() => c.caseId);
  });
  return { count: hits.length, cases: [...new Set(hits)] };
}

export const autogradeLabel = (stale: OutdatedResponses): string => stale.count ? "Replace and autograde" : "Run Autograder";

export function replaceAutogradingNote(stale: OutdatedResponses): string {
  if (!stale.count) return "";
  const judgments = stale.count === 1 ? "1 autograding result" : `${stale.count} autograding results`;
  return ` ${judgments} for ${stale.cases.join(", ")} used a rubric made before the case text was edited. Before autograding, ${stale.count === 1 ? "it moves" : "they move"} to results/superseded/ with ${stale.count === 1 ? "its" : "their"} scores.`;
}

export function replaceNote(outdated: OutdatedResponses): string {
  if (!outdated.count) return "";
  const responses = outdated.count === 1 ? "1 response" : `${outdated.count} responses`;
  return `${responses} for ${outdated.cases.join(", ")} ${outdated.count === 1 ? "was" : "were"} collected for an earlier Task. Before collecting, ${outdated.count === 1 ? "it moves" : "they move"} to results/superseded/ with ${outdated.count === 1 ? "its" : "their"} autograding and scores. Collect every prompt choice again before autograding.`;
}

export function responsesAction(prompt: ChosenPrompt | null, outdated: OutdatedResponses = NO_OUTDATED): ApiPipelineAction {
  return { stage: "responses", ...(prompt ? { prompt: prompt.id } : {}), ...(outdated.count ? { replaceOutdated: true } : {}) };
}

const promptLine = (prompt: ChosenPrompt): string => `Prompt: ${prompt.name}. Text: ${prompt.text}`;

export function responsesProposal(prompt: ChosenPrompt | null, outdated: OutdatedResponses = NO_OUTDATED): string {
  const scope = "All imported cases, using the saved model and trial scope.";
  return [scope, prompt && promptLine(prompt), replaceNote(outdated)].filter(Boolean).join(" ");
}

export function responsesAgentPrompt(base: string, prompt: ChosenPrompt | null, outdated: OutdatedResponses = NO_OUTDATED): string {
  const replace = outdated.count ? ` Responses for ${outdated.cases.join(", ")} were collected for an earlier Task: first move them aside with noharm.py replace-outdated for this project, then collect.` : "";
  return `${base}${replace}${prompt ? ` Collect with the saved prompt by passing --prompt ${prompt.id} to the collection command.` : ""}`;
}

export function responsesAsk(base: string, prompt: ChosenPrompt | null, outdated: OutdatedResponses = NO_OUTDATED): { action: ApiPipelineAction; prompt: string; label: string; apiLead?: string } {
  const lead = [prompt && promptLine(prompt), replaceNote(outdated)].filter(Boolean).join(" ");
  return { action: responsesAction(prompt, outdated), prompt: responsesAgentPrompt(base, prompt, outdated), label: collectLabel(outdated), ...(lead ? { apiLead: lead } : {}) };
}

export type RunPromptView =
  | { state: "loading"; id: string }
  | { state: "ok"; id: string; name: string; text: string }
  | { state: "blocked"; id: string; reason: string };

export function runPromptView(id: string, saved: (ChosenPrompt & { sha256?: string })[], recorded: Record<string, string>): RunPromptView {
  const prompt = saved.find(item => item.id === id);
  if (!prompt) return { state: "blocked", id, reason: `The prompt ${id} is no longer saved in this project, so this run cannot be resumed with it. Start a new run.` };
  if (recorded[id] !== undefined && prompt.sha256 !== recorded[id]) return { state: "blocked", id, reason: `The saved text of ${prompt.name} differs from the text this run's responses were collected with, so this run cannot be resumed. Start a new run.` };
  return { state: "ok", id, name: prompt.name, text: prompt.text };
}

export function plannedModelIds(provenance: Record<string, unknown>): string[] {
  const models = Array.isArray(provenance.models) ? provenance.models.filter((model): model is string => typeof model === "string") : [];
  const inference = provenance.inference as { set_prompts?: Record<string, unknown> } | undefined;
  const prompted = new Set(Object.keys(inference?.set_prompts ?? {}));
  return models.filter(model => !prompted.has(model));
}

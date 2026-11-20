// What the user pastes into their coding agent. The UI never shows a command line.
export type PromptKey = "create" | "import" | "rubrics" | "responses" | "autograding" | "scores" | "fixRubric" | "fixAutograding" | "staleAutograding" | "useReviewedRubric";

export const TEXT_V2_DRAFT_GUIDANCE = "Use the current text rubric format: C1 usual care, C2 follow-up, and criteria with a Cn.0 omission item. Separate complete main approaches from addOn: true extras. Give usual care and every item explicit 1-9 Clinical Appropriateness and none/mild/moderate/severe Error Severity. Preserve prior drafts and use a fresh run slot.";

export function agentPrompt(key: PromptKey, caseId?: string, project?: string): string {
  const target = project ? `the ${project} project` : "the project";
  const scope = `${caseId ? `item ${caseId}` : "every item"}${project ? ` in ${target}` : ""}`;
  switch (key) {
    case "create": return "Create a new project and import inputs and references into it.";
    case "import": return `Import inputs and references into ${target}.`;
    case "rubrics": return `Draft rubrics for ${scope}. ${TEXT_V2_DRAFT_GUIDANCE}`;
    case "responses": return `Collect independent model responses for ${scope}.`;
    case "autograding": return `Run autograding for ${scope} after checking for existing judgment receipts. Preserve the selected rubric format and the judge rules pinned for the project. Preserve prior results and use a fresh project/run when needed.`;
    case "scores": return `Compute scores for ${target}. Preserve each stored rubric format: error severities and bounds for text rubrics, existing scoring for legacy answer tables. Check coverage.`;
    case "fixRubric": return `The rubric draft for ${scope} failed validation. Inspect and preserve the failed draft, keep its selected rubric format, and draft again in a fresh run slot.`;
    case "fixAutograding": return `Autograding failed for ${scope}. Inspect and preserve the failed receipts, then help me prepare a fresh project/run for another attempt.`;
    case "staleAutograding": return `Inputs for ${scope} changed after autograding. Preserve the existing results and help me prepare a fresh project/run using the current inputs.`;
    case "useReviewedRubric": return `Preserve the existing autograding for ${scope} and help me prepare a fresh project/run using the reviewed rubric.`;
  }
}

export function modelSelectionHandoff(project: string, plannedModels: string[], selected: string[]): string {
  const existing = [...new Set(plannedModels)];
  const requested = [...new Set(selected)];
  const retained = existing.filter((model) => requested.includes(model));
  const added = requested.filter((model) => !existing.includes(model));
  const removed = existing.filter((model) => !requested.includes(model));
  const list = (models: string[]): string => models.length ? models.map((model) => JSON.stringify(model)).join("\n") : "None.";
  return `For project ${JSON.stringify(project)}, update the planned model selection.\n\nKeep these existing models with their current backends and routes:\n${list(retained)}\n\nAdd these selected models through OpenRouter:\n${list(added)}\n\nRemove only these explicitly deselected models from the planned set:\n${list(removed)}\n\nDo not remove any other models or change existing routes. Preserve stored responses, trials, and run identities. If this change requires a new project/run, explain that before changing the plan. Do not collect responses yet.`;
}

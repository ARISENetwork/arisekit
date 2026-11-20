import type { ReactNode } from "react";
import ModelChecklist from "@/components/mc/ModelChecklist";
import ApiResponseModels, { type ApiResponseSetup } from "@/components/mc/ApiResponseModels";
import { projectTrials, showTrial } from "@/lib/caseset/trials";
import ResponsePromptPicker, { CollectResponses } from "@/components/mc/ResponsePromptPicker";
import ResponsePlan from "@/components/mc/ResponsePlan";
import { LocalResponseSlot, type ResponseView } from "@/components/mc/LocalResponses";
import StepFrame, { caseOf, ResponsePicker, rowOf, StepPanel } from "@/components/mc/StepFrame";
import type { StepProps } from "@/components/mc/StepFrame";
import { OutdatedTag, Prose, Tag } from "@/components/mc/ui";
import { agentPrompt } from "@/lib/caseset/prompts";
import { isTutorialProject } from "@/lib/onboarding";
import { outdatedResponses, plannedModelIds } from "@/lib/response-prompt-picker";
import { modelLabel } from "@/lib/caseset/model-label";


export default function ResponsesStep({ bench, params, modelSelection, apiSetup }: StepProps & { modelSelection?: ReactNode; apiSetup?: ApiResponseSetup }) {
  const c = caseOf(bench, params);
  const r = rowOf(bench, params);
  const ask = <CollectResponses project={bench.name} base={agentPrompt("responses", c.caseId, bench.name)} outdated={outdatedResponses(bench.cases)} />;
  const promptless = bench.name === "__guided-uti__" || isTutorialProject(bench.name);
  const output = (selected: ReturnType<typeof rowOf>) => !selected
    ? <><div><Tag tone="bad">No response</Tag></div>{ask}</>
    : selected.row.responseError
      ? <><div><Tag tone="bad">Error</Tag></div><p className="m-0 break-words font-mc-mono text-[13px] text-mc-bad">{selected.row.responseError}</p>{ask}</>
      : <>{selected.row.outdated && <div><OutdatedTag output="response" reason={selected.row.outdated} /></div>}<Prose>{selected.row.response}</Prose></>;
  const note = (model: string, trial: number) => `${modelLabel(model, c.page.provenance)}${showTrial(bench.trials, trial) ? `, trial ${trial}` : ""}`;
  const models = [...new Set([...c.responses.map((response) => response.row.model), ...bench.models])].sort();
  const plannedModels = plannedModelIds(c.page.provenance);
  const view = (model: string, trial: number): ResponseView => {
    const selected = { ...params, model, trial };
    return { model, trial, output: output(rowOf(bench, selected)), picker: <ResponsePicker bench={bench} params={selected} step="responses" />, note: note(model, trial) };
  };
  // Model switches reset to trial 1. Preserve the opening trial for browser Back.
  const views = models.map((model) => view(model, 1));
  if (params.model && params.trial !== 1) views.push(view(params.model, params.trial));
  const tutorial = bench.name === "__guided-uti__";
  const suggestion = <p className="m-0 text-sm">We suggest <a className="text-mc-accent underline underline-offset-4" href="https://openrouter.ai/docs/quickstart" rel="noreferrer" target="_blank">OpenRouter</a> to test many different models. {tutorial ? modelSelection ? "This preview uses prepared teaching responses." : "This guided tutorial uses prepared teaching responses." : isTutorialProject(bench.name) ? "For this tutorial, we can start with your coding agent using its existing subscription." : ""}</p>;
  const checklist = modelSelection ?? <ModelChecklist key={`${bench.name}:${JSON.stringify(plannedModels)}`} project={bench.name} plannedModels={plannedModels} />;
  // The guided tutorial keeps its teaching layout; projects show the task and a compact plan beside the response.
  const plan = apiSetup
    ? <ApiResponseModels bench={bench} {...apiSetup} />
    : tutorial
      ? <>{!promptless && <StepPanel title="Prompt" compact><ResponsePromptPicker project={bench.name} /></StepPanel>}<StepPanel title="Models to test" compact>
        {suggestion}
        {checklist}
        {models.length > 0 ? <><p className="m-0 text-xs text-mc-muted">Models in this project</p><ul className="m-0 list-disc space-y-1 pl-5 text-sm">{models.map((model) => <li className="break-words" key={model}>{modelLabel(model, c.page.provenance)}</li>)}</ul></> : <p className="m-0 text-xs text-mc-muted">No models added yet. Choose the models in chat before collecting responses.</p>}
      </StepPanel></>
      : <ResponsePlan project={bench.name} models={models.map((model) => modelLabel(model, c.page.provenance))} trials={projectTrials(bench.trials)} promptless={promptless} checklist={<>{suggestion}{checklist}</>} />;
  return (
    <StepFrame
      bench={bench}
      inputsAboveOutput={tutorial}
      inputsTitle={tutorial ? undefined : "Task"}
      inputs={<Prose>{c.prompts[params.itemId] || c.page.source.presentation}</Prose>}
      inputsNote={c.prompts[params.itemId] ? undefined : "No prompt recorded; showing the source input"}
      inputsBelow={plan}
      outputs={<LocalResponseSlot name="output">{output(r)}</LocalResponseSlot>}
      outputsTitle={tutorial ? undefined : "Response"}
      outputsNote={params.model ? note(params.model, params.trial) : undefined}
      localResponses={{ initial: params, views }}
      params={params}
      picker={<LocalResponseSlot name="picker"><ResponsePicker bench={bench} params={params} step="responses" /></LocalResponseSlot>}
      step="responses"
    />
  );
}

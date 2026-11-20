import type { ReactElement } from "react";
import { StepPanel } from "@/components/mc/StepFrame";
import { Tag, type Tone } from "@/components/mc/ui";
import type { ApiModelOption } from "@/lib/api-pipeline-config";
import type { ApiModelTeam } from "@/lib/api-model-teams";
import { defaultReasoningLabel, REASONING_LABELS } from "@/lib/api-model-reasoning";
import { apiResponseRows, type ApiResponseRow, type PromptName } from "@/lib/api-response-status";
import type { Benchmark } from "@/lib/caseset/metrics";
import ResponsePromptPicker from "@/components/mc/ResponsePromptPicker";
import { ModelSetupLink } from "@/components/mc/ApiExecution";

export interface ApiResponseSetup { team: ApiModelTeam | null; models: ApiModelOption[]; catalogError?: string; prompts?: PromptName[]; promptsError?: string; promptsInUse?: boolean }

const STATUS_TONE: Record<ApiResponseRow["status"], Tone> = { Pending: "plain", Complete: "model", Failed: "bad", "Different settings": "draft" };

export default function ApiResponseModels({ bench, team, models, catalogError, prompts, promptsError, promptsInUse }: ApiResponseSetup & { bench: Benchmark }): ReactElement {
  const rows = team ? apiResponseRows(bench, team, prompts) : [];
  const selected = new Set(rows.map(row => row.model));
  const otherSaved = bench.models.some(model => !selected.has(model));
  return <StepPanel title="Models to test" compact note={<ModelSetupLink className="text-mc-accent underline underline-offset-4">{rows.length ? "Edit API setup" : "Set up API models"}</ModelSetupLink>}>
    {rows.length ? <>
      <ResponsePromptPicker project={bench.name} unavailable={promptsError} inUse={promptsInUse} />
      <p className="m-0 text-xs text-mc-muted">Collection across all imported cases and trials.</p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-[13px]">
          <caption className="sr-only">API response models and collection status</caption>
          <thead><tr className="text-xs text-mc-muted"><th scope="col" className="pb-2 pr-3 font-medium">Model</th><th scope="col" className="pb-2 pr-3 font-medium">Reasoning</th><th scope="col" className="pb-2 font-medium">Status</th></tr></thead>
          <tbody>{rows.map(row => {
            const option = models.find(model => model.id === (row.modelId ?? row.id));
            const reasoning = row.reasoning ? REASONING_LABELS[row.reasoning] : option?.reasoning ? defaultReasoningLabel(option.reasoning) : "Model default";
            return <tr className="border-t border-mc-line align-top" key={row.id}>
              <td className="py-3 pr-3"><strong className="block font-medium">{option?.name ?? row.modelId ?? row.id}</strong>{row.prompt && <span className="mt-1 block text-xs text-mc-muted">Prompt: {row.prompt}</span>}{option && <span className="mt-1 block break-all text-xs text-mc-muted">{row.modelId ?? row.id}</span>}</td>
              <td className="py-3 pr-3">{reasoning}</td>
              <td className="py-3"><Tag tone={STATUS_TONE[row.status]}>{row.status}</Tag><span className="mt-1 block text-xs text-mc-muted">{row.completed} / {row.total} collected</span>{row.failed > 0 && <span className="mt-1 block text-xs text-mc-bad">{row.failed} failed</span>}{row.pending > 0 && <span className="mt-1 block text-xs text-mc-muted">{row.pending} pending</span>}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {rows.filter(row => row.mismatch).map(row => <p className="m-0 text-xs text-mc-muted" key={row.id}>{models.find(model => model.id === (row.modelId ?? row.id))?.name ?? row.modelId ?? row.id}{row.prompt ? `, ${row.prompt}` : ""}: {row.mismatch}</p>)}
    </> : <p className="m-0 text-sm text-mc-muted">Choose models in API setup before collecting responses.</p>}
    {catalogError && <p className="m-0 text-xs text-mc-muted">Model details unavailable: {catalogError}. Saved selections and collection status are shown.</p>}
    {otherSaved && <p className="m-0 text-xs text-mc-muted">Other saved responses remain available in the model picker.</p>}
  </StepPanel>;
}

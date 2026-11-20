"use client";

import { useEffect, useId, useRef, useState } from "react";
import PromptBox from "./PromptBox";
import { ModelSetupLink, useApiExecution } from "./ApiExecution";
import { modelSelectionHandoff } from "@/lib/model-selection";
import { modelName, modelOrganization, SUGGESTED_MODELS } from "@/lib/model-names";
import styles from "./GuidedDataset.module.css";


export default function ModelChecklist({ project, plannedModels = [], forceLocal = false }: { project: string; plannedModels?: string[]; forceLocal?: boolean }) {
  const execution = useApiExecution();
  const [selected, setSelected] = useState<string[]>(() => [...new Set(plannedModels)]);
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const copyTarget = useId();
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  const existingModels = [...new Set(plannedModels)].filter((id) => !SUGGESTED_MODELS.some((model) => model.id === id));
  const models = [...existingModels.map((id) => ({ id, name: modelName(id) ?? id, organization: modelOrganization(id) })), ...SUGGESTED_MODELS];
  const prompt = selected.length
    ? modelSelectionHandoff(project, plannedModels, selected)
    : "Select models above to prepare a prompt for your coding agent.";
  const toggle = (id: string): void => {
    setSelected((current) => current.includes(id) ? current.filter((model) => model !== id) : [...current, id]);
  };
  if (!forceLocal && execution?.mode === "api" && execution.project === project && project !== "__guided-uti__") return <>
    <p className="m-0 text-sm text-mc-muted">Choose the models under test and the models for rubric generation and autograding in API model setup.</p>
    <ModelSetupLink className="self-start text-sm font-medium text-mc-accent underline underline-offset-4">{execution.configured ? "Edit API model setup" : "Set up API models"}</ModelSetupLink>
  </>;
  return <>
    {plannedModels.length > 0 && <p className="m-0 text-xs text-mc-muted">Existing models stay selected. Uncheck a model to remove it from the plan.</p>}
    <div className="overflow-x-auto rounded-lg border border-mc-border">
      <table className="w-full text-left text-[13px] leading-4">
        <caption className="sr-only">Model checklist</caption>
        <thead className="bg-mc-bg text-xs text-mc-muted">
          <tr><th scope="col" className="w-12 px-3 py-1"><span className="sr-only">Select</span></th><th scope="col" className="px-3 py-1 font-medium">Organization</th><th scope="col" className="px-3 py-1 font-medium">Model</th></tr>
        </thead>
        <tbody>
          {models.map((model) => <tr key={model.id} className="border-t border-mc-border focus-within:bg-mc-bg">
            <td className="px-3 py-1"><input type="checkbox" checked={selected.includes(model.id)} onChange={() => toggle(model.id)} aria-label={`Select ${model.organization ?? "existing model"} ${model.name}`} className="block h-4 w-4 cursor-pointer accent-[var(--mc-accent)]" /></td>
            <td className="px-3 py-1">{model.organization ?? "Not specified"}</td>
            <td className="px-3 py-1">{model.organization ? <a href={`https://openrouter.ai/${model.id}`} target="_blank" rel="noreferrer" className="text-mc-accent underline underline-offset-4">{model.name}</a> : <span className="break-words">{model.name}</span>}</td>
          </tr>)}
        </tbody>
      </table>
    </div>
    <div className="flex items-center justify-end gap-3">
      <span className="text-xs text-mc-muted">{selected.length ? `${selected.length} selected` : "Select at least one model"}</span>
      <button type="button" disabled={!selected.length} onClick={() => setOpen(true)} className="w-44 shrink-0 rounded-md border border-mc-accent bg-mc-accent px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-40">Copy model selection</button>
    </div>
    <dialog ref={dialog} className={styles.dialog} onCancel={() => setOpen(false)} aria-label="Model selection handoff">
      <header className={styles.dialogHeading}><h2>Paste this into your coding agent</h2><div className={styles.dialogHeaderActions}><span id={copyTarget} /><button type="button" onClick={() => setOpen(false)}>Close</button></div></header>
      <PromptBox key={prompt} prompt={prompt} lead="Copy this prompt and paste it into your coding agent. Come back once your coding agent finishes." copyLabel="Copy prompt" copyButtonTarget={copyTarget} miniCopy />
    </dialog>
  </>;
}

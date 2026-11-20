"use client";

import { useEffect, useId, useMemo, useRef, useState, type ReactElement } from "react";
import Link from "@/components/MotionLink";
import Dropdown from "@/components/Dropdown";
import ApiReadinessNotice from "./ApiReadiness";
import type { ApiConfigImpact } from "@/lib/api-config-impact";
import { useApiExecution } from "./ApiExecution";
import type { ApiModelOption, ApiPipelineConfig } from "@/lib/api-pipeline-config";
import { initialModelTeams, createApiPipelineConfig, toggleTeamModel, setTeamReasoning, type ApiModelStage, type ApiModelTeam } from "@/lib/api-model-teams";
import { defaultReasoningLabel, REASONING_LABELS, type ReasoningEffort } from "@/lib/api-model-reasoning";
import { recommendedModels } from "@/lib/api-model-shortlist";
import { noharmHref } from "@/lib/noharm-path";
import styles from "./ApiModelSetup.module.css";

const stages: { id: ApiModelStage; title: string; description: string; integration: string; optional?: boolean }[] = [
  { id: "generation", title: "Rubric generation", description: "Draft criteria, main approaches, and add-ons from each Task and Solution.", integration: "Combine the drafts into one rubric." },
  { id: "rating", title: "Harm rating", description: "Rate Clinical Appropriateness and Error Severity for usual care and every item. Optional.", integration: "Reconcile explicit scores and severities without changing criteria or add-on roles.", optional: true },
  { id: "responses", title: "Models under test", description: "Collect each model's independent response for every case and trial.", integration: "" },
  { id: "judge", title: "Autograding", description: "Map each response to rubric items with supporting evidence.", integration: "Reconcile the evidence mappings without changing rubric ratings." },
];

function price(value: string | null): string {
  return value !== null && value.trim() && Number.isFinite(Number(value)) && Number(value) >= 0
    ? `$${(Number(value) * 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 6 })}` : "not listed";
}

function ModelName({ id, models }: { id: string; models: ApiModelOption[] }): ReactElement {
  const model = models.find(option => option.id === id);
  return <span className={styles.modelName}><strong>{model?.name ?? id}</strong><span>{id}{!model && " (unavailable)"}</span></span>;
}

export function ReasoningSelect({ model, value, label, onChange }: { model?: ApiModelOption; value?: ReasoningEffort; label: string; onChange: (effort: ReasoningEffort | "") => void }): ReactElement | null {
  const id = useId();
  if (!model?.reasoning) return null;
  return <div className={styles.reasoning}><label htmlFor={id}>Reasoning</label><Dropdown id={id} className={styles.reasoningSelect} aria-label={label} value={value ?? ""} onChange={event => onChange(event.target.value as ReasoningEffort | "")}>
    <option value="">{defaultReasoningLabel(model.reasoning)}</option>
    {model.reasoning.efforts.map(effort => <option key={effort} value={effort}>{REASONING_LABELS[effort]}</option>)}
  </Dropdown></div>;
}

function RemoveIcon(): ReactElement {
  return <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m4 4 8 8M12 4l-8 8" /></svg>;
}

function CatalogPicker({ panelId, open, label, models, selected, single, onSelect, onClose }: { panelId: string; open: boolean; label: string; models: ApiModelOption[]; selected: string[]; single: boolean; onSelect: (id: string) => void; onClose: () => void }): ReactElement {
  const [search, setSearch] = useState("");
  const [list, setList] = useState<"recommended" | "all">("recommended");
  const input = useRef<HTMLInputElement>(null);
  const recommendedButton = useRef<HTMLButtonElement>(null);
  const id = useId();
  const [rendered, setRendered] = useState(open);
  const recommended = useMemo(() => recommendedModels(models), [models]);
  const showAll = list === "all";
  const visible = useMemo(() => models.filter(model => `${model.id} ${model.name}`.toLowerCase().includes(search.toLowerCase().trim())), [models, search]);
  useEffect(() => {
    if (open) { setRendered(true); (showAll ? input : recommendedButton).current?.focus({ preventScroll: true }); return; }
    const timer = window.setTimeout(() => { setRendered(false); setSearch(""); setList("recommended"); }, 200);
    return () => window.clearTimeout(timer);
  }, [open, showAll]);
  const options = (items: ApiModelOption[], compact: boolean): ReactElement[] => items.map(model => <label className={styles.catalogOption} data-selected={selected.includes(model.id)} key={model.id} title={model.id}>
    <input type={single ? "radio" : "checkbox"} name={single ? `${id}-${compact ? "recommended" : "all"}` : undefined} checked={selected.includes(model.id)} onChange={() => onSelect(model.id)} aria-label={compact ? model.name : `${model.name} (${model.id})`} />
    <span className={styles.catalogText}><strong>{model.name}</strong>{!compact && <span>{model.id}</span>}<span className={styles.pricing}>Input {price(model.inputPrice)} / output {price(model.outputPrice)} per 1M tokens</span></span>
  </label>);
  return <div id={panelId} className={styles.disclosure} data-open={open} inert={!open || undefined} aria-hidden={!open || undefined}>
    <div className={styles.disclosureInner}><div className={styles.picker} role="group" aria-label={label} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); } else if (event.key === "Enter" && event.target instanceof HTMLInputElement && event.target.type === "search") event.preventDefault(); }}>
      <div className={styles.listSwitch} role="group" aria-label="Model lists"><button ref={recommendedButton} type="button" aria-pressed={!showAll} onClick={() => setList("recommended")}>Recommended <span>{recommended.length}</span></button><button type="button" aria-pressed={showAll} onClick={() => setList("all")}>All models <span>{models.length}</span></button></div>
      {!showAll && <p className={styles.shortlistNote}>A starting shortlist across major providers.</p>}
      <div className={styles.disclosure} data-open={showAll} inert={!showAll || undefined} aria-hidden={!showAll || undefined}><div className={styles.disclosureInner}>
        <label className={styles.searchLabel} htmlFor={id}>Search all models</label>
        <input ref={input} id={id} className={styles.searchInput} type="search" placeholder="Model name or provider" value={search} onChange={event => setSearch(event.target.value)} />
      </div></div>
      <div className={styles.catalogStack}>
        <div className={styles.catalog} data-active={!showAll} inert={showAll || undefined} aria-hidden={showAll || undefined} role="group" aria-label="Recommended models">
          {rendered && options(recommended, true)}
          {!recommended.length && <p className={styles.empty}>No shortlist models are available. Switch to All models.</p>}
        </div>
        <div className={styles.catalog} data-active={showAll} inert={!showAll || undefined} aria-hidden={!showAll || undefined} role="group" aria-label="All models">
          {rendered && options(visible, false)}
          {!visible.length && <p className={styles.empty}>No matching models. Try another name or provider.</p>}
        </div>
      </div>
      <div className={styles.pickerFooter}><span role="status">{selected.length} selected across both lists.{showAll && ` ${visible.length} matches.`}</span><button type="button" className={styles.done} onClick={onClose}>Done</button></div>
    </div></div>
  </div>;
}

export function ModelTeamEditor({ stage, title, integration, team, models, onChange }: { stage: ApiModelStage; title: string; integration: string; team: ApiModelTeam; models: ApiModelOption[]; onChange: (team: ApiModelTeam) => void }): ReactElement {
  const [picker, setPicker] = useState<"models" | "integrator" | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const modelTrigger = useRef<HTMLButtonElement>(null);
  const integratorTrigger = useRef<HTMLButtonElement>(null);
  const multiple = team.models.length > 1;
  const close = (): void => { (picker === "integrator" ? integratorTrigger : modelTrigger).current?.focus({ preventScroll: true }); setPicker(null); };
  useEffect(() => {
    if (!picker) return;
    const outside = (event: PointerEvent): void => { if (!host.current?.contains(event.target as Node)) setPicker(null); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [picker]);
  const toggle = (id: string): void => {
    const next = toggleTeamModel(team, id);
    if (next.models.length < 2 && picker === "integrator") setPicker(null);
    onChange(next);
  };
  return <div className={styles.team} ref={host}>
    <div className={styles.teamHeading}><span>{team.models.length ? `${team.models.length} model${team.models.length === 1 ? "" : "s"}` : "No models selected"}</span><button ref={modelTrigger} type="button" className={styles.addModels} aria-label={`Select ${title.toLowerCase()}${stage === "responses" ? "" : " models"}`} aria-controls={`${stage}-models-catalog`} aria-expanded={picker === "models"} onClick={() => setPicker(picker === "models" ? null : "models")}><svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M8 3v10M3 8h10" /></svg>Select models</button></div>
    <ul className={styles.roster} aria-label={`${title} selected models`}>{team.models.map(id => <li key={id}><ModelName id={id} models={models} /><ReasoningSelect model={models.find(model => model.id === id)} value={team.modelReasoning?.[id]} label={`${title} reasoning for ${id}`} onChange={effort => onChange(setTeamReasoning(team, "modelReasoning", id, effort))} /><button type="button" className={styles.remove} aria-label={`Remove ${id} from ${title.toLowerCase()}`} onClick={() => { modelTrigger.current?.focus({ preventScroll: true }); toggle(id); }}><RemoveIcon /></button></li>)}</ul>
    <CatalogPicker panelId={`${stage}-models-catalog`} open={picker === "models"} label={`${title} model catalog`} models={models} selected={team.models} single={false} onSelect={toggle} onClose={close} />
    {stage !== "responses" && <div className={styles.disclosure} data-open={multiple} inert={!multiple || undefined} aria-hidden={!multiple || undefined}>
      <div className={styles.disclosureInner}><div className={styles.integrator}>
        <div className={styles.integratorHeading}><label htmlFor={`${stage}-integrator`}>Integrator <span>Required for multiple models</span></label><button ref={integratorTrigger} id={`${stage}-integrator`} type="button" className={styles.chooseIntegrator} aria-label={`Choose ${title.toLowerCase()} integrator`} aria-controls={`${stage}-integrator-catalog`} aria-expanded={picker === "integrator"} onClick={() => setPicker(picker === "integrator" ? null : "integrator")}>{team.integrator ? "Change" : "Choose model"}</button></div>
        {team.integrator && <div className={styles.integratorModel}><ModelName id={team.integrator} models={models} /><ReasoningSelect model={models.find(model => model.id === team.integrator)} value={team.integratorReasoning?.[team.integrator]} label={`${title} integrator reasoning for ${team.integrator}`} onChange={effort => onChange(setTeamReasoning(team, "integratorReasoning", team.integrator, effort))} /><button type="button" className={styles.remove} aria-label={`Clear ${title.toLowerCase()} integrator`} onClick={() => { integratorTrigger.current?.focus({ preventScroll: true }); onChange({ ...team, integrator: "" }); }}><RemoveIcon /></button></div>}
        <p>{integration}</p>
        <CatalogPicker panelId={`${stage}-integrator-catalog`} open={picker === "integrator"} label={`${title} integrator catalog`} models={models} selected={team.integrator ? [team.integrator] : []} single onSelect={id => onChange({ ...team, integrator: id })} onClose={close} />
      </div></div>
    </div>}
  </div>;
}

// In a popup, the setup closes instead of linking back to Dataset, and a plain save stays on the current page.
export interface ModelSetupPopupControls { titleId: string; onClose: () => void; onSaved: (href: string | undefined, newRun: boolean) => void }

export default function ApiModelSetup({ project, models, initialConfig, editable = true, catalogError, popup }: { project: string; models: ApiModelOption[]; initialConfig?: ApiPipelineConfig | null; editable?: boolean; catalogError?: string; popup?: ModelSetupPopupControls }): ReactElement {
  const [teams, setTeams] = useState(() => initialModelTeams(initialConfig));
  const [impact, setImpact] = useState<ApiConfigImpact | null>(null);
  const [fork, setFork] = useState(false);
  const [runName, setRunName] = useState(`${project.slice(0, 52)}-run`);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const execution = useApiExecution();
  const busy = saving || Boolean(execution?.active);
  const save = async (newRun = false): Promise<void> => {
    if (busy || !editable) return;
    setError(null);
    try {
      const config = createApiPipelineConfig(teams);
      setSaving(true);
      const response = await fetch(newRun ? "/api/pipeline/config/fork" : "/api/pipeline/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, config, ...(newRun ? { name: runName } : {}) }) });
      const result = await response.json() as { href?: string; error?: string; impact?: ApiConfigImpact };
      if (result.impact) { setImpact(result.impact); setFork(true); setSaving(false); return; }
      if (!response.ok) throw new Error(result.error ?? `Model setup returned HTTP ${response.status}.`);
      if (popup) { setSaving(false); popup.onSaved(result.href, newRun); return; }
      window.location.assign(result.href ?? noharmHref("/dataset"));
    } catch (caught) { setError((caught as Error).message); setSaving(false); }
  };
  return <div className={styles.page}>
    <header className={styles.header}>{popup
      ? <div className={styles.popupHeading}><h2 id={popup.titleId}>API model setup</h2><button type="button" className={styles.close} aria-label="Close model setup" onClick={popup.onClose}><RemoveIcon /></button></div>
      : <h1>API model setup</h1>}<p>Choose models for each step in {project}. Integrators combine drafts for rubric generation, rating, and autograding. Models under test respond independently.</p></header>
    <ApiReadinessNotice />
    {!editable && <p className={styles.notice}>API setup is available for your own projects in API Mode. <Link href={noharmHref("/welcome")}>Choose a project and mode</Link>.</p>}
    <form className={styles.page} onSubmit={event => { event.preventDefault(); void save(fork); }}>
      {catalogError && <p className={styles.error} role="alert">Catalog unavailable: {catalogError}</p>}
      <fieldset className={styles.configFields} disabled={busy || !editable}>
      <div className={styles.rows}>{stages.map(stage => <section className={styles.row} key={stage.id}>
        <div className={styles.stage}><h2>{stage.title}</h2><p>{stage.description}</p>{!teams[stage.id].models.length && stage.optional && <p>Skipped when no models are selected.</p>}</div>
        <ModelTeamEditor stage={stage.id} title={stage.title} integration={stage.integration} team={teams[stage.id]} models={models} onChange={team => { setTeams(current => ({ ...current, [stage.id]: team })); setError(null); setImpact(null); }} />
      </section>)}<section className={styles.row}><div className={styles.stage}><h2>Scores</h2><p>Compute scores from the rubric and autograding.</p></div><p className={styles.deterministic}>Deterministic. No model or integrator needed.</p></section></div>
      </fieldset>
      <p className={styles.notice}>Saving changes future steps. Existing rubrics, model responses, autograding, and scores keep their original settings. Changing models under test or their reasoning after collection requires a new run.</p>
      <div className={styles.disclosure} data-open={fork} inert={!fork || undefined} aria-hidden={!fork || undefined}><div className={styles.disclosureInner}><div className={styles.notice}>
        {impact && <><strong>New run required</strong><ul>{impact.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></>}
        <p>The new run copies Tasks, Solutions, and existing rubrics with their provenance. It starts with no model responses, autograding, or scores. The original project and its settings stay intact. No models run when you create it.</p>
        <label htmlFor="new-run-name">New run name</label><input id="new-run-name" className={styles.searchInput} value={runName} onChange={event => setRunName(event.target.value)} pattern="[a-z0-9][a-z0-9-]{0,63}" maxLength={64} required={fork} disabled={!fork || busy || !editable} />
      </div></div></div>
      {error && <p className={styles.error} role="alert">{error}</p>}
      <div className={styles.actions}><button className={styles.primary} type="submit" disabled={busy || !editable || Boolean(catalogError)}>{saving ? fork ? "Creating…" : "Saving…" : fork ? "Create new run" : "Save and continue"}</button><button type="button" className={styles.done} disabled={busy || !editable} onClick={() => { setFork(!fork); setImpact(null); setError(null); }}>{fork ? "Keep editing original setup" : "Create new run"}</button>{popup ? <button type="button" className={styles.back} onClick={popup.onClose}>Cancel</button> : <Link className={styles.back} href={noharmHref("/dataset")}>Return to Dataset</Link>}<span className={styles.saveNote}>Saving does not run models.</span></div>
    </form>
  </div>;
}

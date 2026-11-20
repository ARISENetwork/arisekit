"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import Link from "@/components/MotionLink";

import StepHeading from "@/components/mc/StepHeading";
import PromptBox from "@/components/mc/PromptBox";
import { ApiStageAction, useApiExecution } from "@/components/mc/ApiExecution";
import { pipelineSourceId } from "@/lib/api-pipeline-action";
import { parseDataset, rubricHandoff, uploadedDatasetHandoff, type DatasetCase } from "@/lib/dataset-import";
import type { DatasetUpload } from "@/lib/dataset-upload";
import { stepHref, type StepParams } from "@/lib/caseset/routes";
import type { TutorialDataset } from "@/lib/uti-tutorial";

import actionStyles from "./StageActions.module.css";
import StageActionPlacement from "./StageActionPlacement";
import styles from "./GuidedDataset.module.css";
import workspaceStyles from "./WelcomeWorkspace.module.css";

export default function GuidedDataset({ example: tutorialExample, prepared = false, onNext, onGenerateRequest, animateField, onTyping, project, initialCase, editableSavedCase = false, originalCase, readOnly = false, controls, savedActions, onDraftChange, onBeforeGenerate, onCaseSaved, onAddAlternative, sources = [], previewActions, nextParams, separateIntake = false }: { nextParams?: StepParams; separateIntake?: boolean; previewActions?: { generate: () => void; import: () => void }; example: TutorialDataset; onCaseSaved?: (value: DatasetCase) => void; onBeforeGenerate?: () => Promise<boolean>; onAddAlternative?: () => void; initialCase?: DatasetCase; editableSavedCase?: boolean; originalCase?: DatasetCase; readOnly?: boolean; controls?: ReactNode; savedActions?: ReactNode; onDraftChange?: (value: DatasetCase) => void; sources?: { filename: string; path: string; processed: boolean }[]; project?: string; prepared?: boolean; onNext?: () => void; onGenerateRequest?: () => void; animateField?: "task" | "solution" | "alternative" | "errors"; onTyping?: (typing: boolean) => void }) {
  const router = useRouter();
  const execution = useApiExecution();
  const api = !prepared && !previewActions && execution?.mode === "api" && execution.project === project;
  const formId = useId();
  const [input, setInput] = useState(initialCase?.task ?? "");
  const [solutions, setSolutions] = useState(initialCase?.solutions ?? [""]);
  const [errors, setErrors] = useState(initialCase?.errors ?? "");
  const [uploaded, setUploaded] = useState<DatasetUpload | null>(null);
  const savedBasis = useRef(originalCase);
  const [projects, setProjects] = useState<string[]>([]);
  const [destinationProject, setDestinationProject] = useState(project ?? "");
  const [modal, setModal] = useState<"import" | "generate" | "sources" | null>(null);
  const [retainedModal, setRetainedModal] = useState<"import" | "generate" | "sources">("import");
  const displayedModal = modal ?? retainedModal;
  const [importError, setImportError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => { if (modal) { setRetainedModal(modal); dialog.current?.showModal(); } else dialog.current?.close(); }, [modal]);
  useEffect(() => {
    if (modal !== "import") return;
    const controller = new AbortController();
    const load = async (): Promise<void> => {
      try {
        const response = await fetch("/api/dataset-upload", { signal: controller.signal, cache: "no-store" });
        const payload = await response.json() as { projects: string[]; error?: string };
        if (!response.ok) throw new Error(payload.error);
        setProjects(payload.projects);
      } catch (caught) { if (!controller.signal.aborted) setImportError((caught as Error).message); }
    };
    void load();
    return () => controller.abort();
  }, [modal]);
  const currentCases = (): DatasetCase[] => {
    return [{ ...(initialCase?.source_item_id ? { source_item_id: initialCase.source_item_id } : {}), ...(initialCase?.id ? { id: initialCase.id } : {}), task: input, solutions: solutions.filter((solution) => solution.trim()), errors }];
  };
  const importFile = async (file: File): Promise<void> => {
    if (api && execution.active) return;
    if (!destinationProject) { setImportError("Choose the destination project first."); return; }
    if (api && destinationProject !== project) { setImportError("Choose this project as the destination before running its pipeline."); return; }
    setImporting(true); setImportError(null);
    try {
      const form = new FormData(); form.set("project", destinationProject); form.set("file", file);
      const response = await fetch("/api/dataset-upload", { method: "POST", body: form });
      const payload = await response.json() as DatasetUpload & { error?: string };
      if (!response.ok) throw new Error(payload.error);
      setUploaded(payload);
      if (api) {
        if (payload.project !== project) throw new Error("The saved dataset belongs to another project. Open that project to run it.");
        setModal("generate");
      } else setModal("generate");
    } catch (caught) { setImportError((caught as Error).message); }
    finally { setImporting(false); if (fileInput.current) fileInput.current.value = ""; }
  };
  const generateRubric = async (): Promise<void> => {
    if (typingField || importing || api && execution.active) return;
    if (onBeforeGenerate && !await onBeforeGenerate()) return;
    try { if (!uploaded) parseDataset(JSON.stringify(currentCases()), "dataset.json"); }
    catch (caught) { setError((caught as Error).message); return; }
    setError(null);
    let source = uploaded;
    if (project && editableSavedCase && !uploaded) {
      setImporting(true);
      try {
        const value = currentCases()[0];
        const response = await fetch("/api/dataset-case", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, id: initialCase!.id, value, basis: savedBasis.current }) });
        const payload = await response.json() as { error?: string };
        if (!response.ok) throw new Error(payload.error);
        savedBasis.current = value;
        onCaseSaved?.(value);
        router.refresh();
      } catch (caught) { setError((caught as Error).message); return; }
      finally { setImporting(false); }
    } else if (project && !prepared && !uploaded) {
      setImporting(true);
      try {
        const file = new File([JSON.stringify(currentCases(), null, 2)], `${initialCase?.id ?? "cases"}.json`, { type: "application/json" });
        const form = new FormData(); form.set("project", project); form.set("file", file);
        const response = await fetch("/api/dataset-upload", { method: "POST", body: form });
        const payload = await response.json() as DatasetUpload & { error?: string };
        if (!response.ok) throw new Error(payload.error);
        setUploaded(payload);
        source = payload;
      } catch (caught) { setError((caught as Error).message); return; }
      finally { setImporting(false); }
    }
    if (previewActions) { previewActions.generate(); return; }
    if (api) {
      try {
        if (source && source.project !== project) throw new Error("The saved dataset belongs to another project. Open that project to run it.");
        await execution.run(source ? { stage: "generate", sourceId: pipelineSourceId(source.path) } : { stage: "generate", caseIds: [initialCase!.id!] });
      } catch (caught) { setError((caught as Error).message); }
      return;
    }
    onGenerateRequest?.(); setModal("generate");
  };
  const draftChanged = useRef(onDraftChange);
  draftChanged.current = onDraftChange;
  useEffect(() => { draftChanged.current?.({ ...(initialCase?.source_item_id ? { source_item_id: initialCase.source_item_id } : {}), ...(initialCase?.id ? { id: initialCase.id } : {}), task: input, solutions, errors }); }, [input, solutions, errors, initialCase?.id]);
  const [usingTutorial, setUsingTutorial] = useState(prepared);
  const [error, setError] = useState<string | null>(null);
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  const [removingIndex, setRemovingIndex] = useState<number | null>(null);
  const removalTimer = useRef<number | null>(null);
  const completedFields = useRef(new Set<string>());
  const [typingField, setTypingField] = useState<string | null>(null);
  useEffect(() => {
    if (!prepared || !animateField || completedFields.current.has(animateField)) return;
    const text = tutorialExample[animateField];
    const write = (value: string): void => {
      if (animateField === "task") setInput(value);
      else if (animateField === "solution") setSolutions((previous) => [value, ...previous.slice(1)]);
      else if (animateField === "alternative") setSolutions((previous) => [previous[0], value, ...previous.slice(2)]);
      else setErrors(value);
    };
    const finish = (): void => { completedFields.current.add(animateField); setTypingField(null); onTyping?.(false); };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { write(text); finish(); return; }
    setTypingField(animateField); onTyping?.(true); write("");
    let length = 0;
    const timer = window.setInterval(() => { length += 2; write(text.slice(0, length)); if (length >= text.length) { window.clearInterval(timer); finish(); } }, 16);
    return () => window.clearInterval(timer);
  }, [prepared, animateField, onTyping]);
  useEffect(() => {
    if (focusIndex !== null) document.getElementById(focusIndex === 0 ? "example-reference" : `example-solution-${focusIndex}`)?.focus();
  }, [solutions.length, focusIndex]);
  useEffect(() => () => { if (removalTimer.current !== null) window.clearTimeout(removalTimer.current); }, []);

  const useExample = (): void => {
    setUploaded(null);
    setUsingTutorial(true);
    setInput(tutorialExample.task);
    setSolutions([tutorialExample.solution]);
    setErrors(tutorialExample.errors);
    setFocusIndex(0);
    setError(null);
  };

  const addSolution = (): void => {
    setUploaded(null);
    setFocusIndex(solutions.length);
    setSolutions((previous) => [...previous, ""]);
  };
  const removeSolution = (index: number): void => {
    if (solutions.length <= 1 || removingIndex !== null) return;
    setUploaded(null);
    setRemovingIndex(index);
    const delay = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 180;
    removalTimer.current = window.setTimeout(() => {
      setSolutions((previous) => previous.filter((_, at) => at !== index));
      setFocusIndex(Math.min(index, solutions.length - 2));
      setRemovingIndex(null);
      removalTimer.current = null;
    }, delay);
  };

  const importAction = <button className={styles.sourceAction} disabled={Boolean(typingField) || Boolean(api && execution.active)} onClick={() => { if (previewActions) { previewActions.import(); return; } setImportError(null); setModal("import"); }} type="button">Bulk Upload</button>;
  const exampleAction = !readOnly && !editableSavedCase && <button className={styles.useExample} disabled={removingIndex !== null} onClick={useExample} title="Fill the fields with the tutorial example" type="button">Use Example</button>;

  return <><div className={workspaceStyles.previewSwitch}>
    <section aria-label="Dataset draft" className={`${workspaceStyles.previewPane} ${styles.dataset}`} data-active data-button-layout={separateIntake ? "separated" : undefined}>
      <header className={styles.heading}>
        <div className="mb-5 flex flex-wrap items-start gap-3.5"><StepHeading step="cases" /></div>
        <div className={styles.workspaceControls}>{controls}<div className={styles.headingActions}>{importAction}{sources.length > 0 && <button className={styles.sourceAction} type="button" onClick={() => setModal("sources")}>Uploaded sources ({sources.length})</button>}{!separateIntake && exampleAction}</div>
        </div>
      </header>
      {uploaded && <p className={styles.uploadedFile}>Saved {uploaded.filename} in {uploaded.project}. {api ? "Pipeline status appears above." : "Awaiting processing by your coding agent."}</p>}
      <form id={formId} className={styles.form} onChange={() => setUploaded(null)} onSubmit={(event) => { event.preventDefault(); if (!readOnly) void generateRubric(); }}>
        <fieldset className={styles.fields} disabled={Boolean(api && execution.active) || importing}>
          <div className={styles.input}>
            {separateIntake ? <div className={styles.taskHeading}><label htmlFor="example-input">Task</label>{exampleAction}</div> : <label htmlFor="example-input">Task</label>}
            <p>The case, prompt, or question you will give to the language model (LLM).</p>
            <textarea id="example-input" readOnly={readOnly || typingField === "task"} onChange={(event) => setInput(event.target.value)} placeholder={prepared ? "" : `Example: ${tutorialExample.task}`} required={!uploaded} value={input} />
          </div>
          <div className={styles.reference}>
            <div className={styles.referenceHeading}><label htmlFor="example-reference">Solution</label>
<button data-tutorial-add-solution className={styles.addSolution} disabled={importing || removingIndex !== null} onClick={readOnly ? onAddAlternative : addSolution} type="button">Add alternative solution</button></div>
            <p>Appropriate responses. &quot;Add alternative solution&quot; if multiple acceptable alternatives</p>
            <div className={styles.solutions}>
              {solutions.map((solution, index) => <div className={styles.solution} data-removing={removingIndex === index} inert={removingIndex === index} key={index}>
                {solutions.length > 1 ? <div className={styles.solutionHeader}>
                  <label className={styles.solutionLabel} htmlFor={index === 0 ? "example-reference" : `example-solution-${index}`}>Solution {index + 1}</label>
                  <button aria-label={`Remove solution ${index + 1}`} className={styles.removeSolution} disabled={readOnly || removingIndex !== null} onClick={() => removeSolution(index)} title={`Remove solution ${index + 1}`} type="button">
                    <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="m4 4 8 8M12 4l-8 8" /></svg>
                  </button>
                </div> : <label className="sr-only" htmlFor="example-reference">Solution 1</label>}
                <textarea id={index === 0 ? "example-reference" : `example-solution-${index}`} readOnly={readOnly || index === 0 && typingField === "solution" || index === 1 && typingField === "alternative"} onChange={(event) => { setSolutions((previous) => previous.map((value, at) => at === index ? event.target.value : value)); }} placeholder={prepared ? "" : index === 0 ? `Example: ${tutorialExample.solution}` : "Example: TMP-SMX is an alternative if local resistance allows. Obtain the same tests and advise urgent care for fever, flank pain, nausea, or worsening symptoms."} required={index === 0 && !uploaded} value={solution} />
              </div>)}
            </div>
          </div>
          <div className={styles.errors}>
            <label htmlFor="example-errors">Errors <span className={styles.optional}>(optional but recommended)</span></label>
            <p>Possible errors and their potential severity</p>
            <textarea id="example-errors" readOnly={readOnly || typingField === "errors"} onChange={(event) => setErrors(event.target.value)} placeholder={readOnly ? "No errors provided." : prepared ? "" : `Example:\n${tutorialExample.errors}`} value={errors} />
          </div>
        </fieldset>
        <div className={styles.bottomActions} data-development={process.env.NODE_ENV === "development"} data-docked={Boolean(savedActions) || !prepared}>
          {savedActions ?? <StageActionPlacement active={!prepared}><div className={actionStyles.actions}>
            <button data-generate-rubric form={formId} className={actionStyles.primary} disabled={Boolean(typingField) || importing || Boolean(api && execution.active) || removingIndex !== null || !uploaded && (!input.trim() || !solutions[0].trim())} type="submit">{api && execution.active ? "Pipeline running…" : importing ? "Saving source…" : "Generate Rubric"}</button>
            {!prepared && project && <Link href={stepHref("rubrics", { case: nextParams?.caseId ?? initialCase?.id, version: nextParams?.version, item: nextParams?.itemId, model: nextParams?.model, trial: nextParams?.trial })}>Next</Link>}
          </div></StageActionPlacement>}
        </div>
        {error && <p className={styles.error} role="alert">{error}</p>}
      </form>
    </section>
  </div><dialog ref={dialog} className={styles.dialog} onCancel={() => setModal(null)} aria-labelledby="dataset-dialog-title">
    <header className={styles.dialogHeading}><h2 id="dataset-dialog-title">{displayedModal === "import" ? "Import dataset" : displayedModal === "sources" ? "Uploaded sources" : api ? "Generate rubrics" : "Paste this into your coding agent"}</h2><div className={styles.dialogHeaderActions}><span id="dataset-copy-action" /><button type="button" onClick={() => setModal(null)}>Close</button></div></header>
    {displayedModal === "sources" ? <div className={styles.sources}>{sources.map((source) => <div key={source.path}>
      <strong>{source.filename}</strong><p>{source.processed ? "Processed" : "Awaiting processing"}</p>
      {!source.processed && <ApiStageAction project={project!} action={{ stage: "generate", sourceId: api ? pipelineSourceId(source.path) : source.path }} label="Import and generate rubrics" prompt={uploadedDatasetHandoff(project!, source.path)} lead="Process this source with your coding agent." beforeRun={() => setModal(null)} miniCopy />}
    </div>)}</div> : displayedModal === "import" ? <>
      <p>Upload a CSV or JSON file with multiple cases. Your file should have 3 fields: Task, Solution, and Errors. For CSV, concatenate multiple acceptable solutions into one Solution field, with &quot;SOLUTION:&quot; as a separator. {api ? "Uploading saves the source. Start rubric generation separately when ready." : "This file will be imported into your project for your coding agent to process"}</p>
      <label className={styles.projectDestination}>Project<select aria-label="Destination project" value={destinationProject} disabled={importing || api} onChange={(event) => setDestinationProject(event.target.value)}><option value="">Choose a project</option>{projects.map((project) => <option key={project} value={project}>{project}</option>)}</select></label>
      <div className={styles.dropZone} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (!importing && event.dataTransfer.files[0]) void importFile(event.dataTransfer.files[0]); }}><p>{importing ? "Saving dataset…" : "Drop a CSV or JSON file here"}</p><button type="button" disabled={importing || !destinationProject} onClick={() => fileInput.current?.click()}>Choose file</button><input ref={fileInput} type="file" accept=".csv,.json" aria-label="Dataset file" hidden onChange={(event) => { if (event.target.files?.[0]) void importFile(event.target.files[0]); }} /></div>
      {importError && <p className={styles.error} role="alert">{importError}</p>}
    </> : <>
      {uploaded && <p className={styles.uploadedFile}>Saved to <code>{uploaded.path}</code></p>}
      {api && uploaded ? <ApiStageAction project={project!} action={{ stage: "generate", sourceId: pipelineSourceId(uploaded.path) }} label="Import and generate rubrics" apiLead="This uses your saved API models and OpenRouter credits." prompt={uploadedDatasetHandoff(uploaded.project, uploaded.path)} beforeRun={() => setModal(null)} /> : <PromptBox prompt={uploaded ? uploadedDatasetHandoff(uploaded.project, uploaded.path) : editableSavedCase ? `Use noharm-rubrics for project ${JSON.stringify(project)}. Generate one draft rubric for item ${initialCase!.id}.` : rubricHandoff(currentCases(), null, prepared && usingTutorial && input === tutorialExample.task, project)} lead={prepared ? "Copy this prompt and paste it into Codex or Claude Code." : "Copy this prompt and paste it into Codex or Claude Code. Come back once your coding agent finishes."} copyLabel="Copy prompt" copyButtonTarget="dataset-copy-action" miniCopy />}
      {prepared && <div className={styles.dialogActions}><button type="button" onClick={() => { setModal(null); onNext?.(); }}>View example rubric</button></div>}
    </>}
  </dialog></>;
}

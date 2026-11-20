"use client";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMotionNavigation } from "@/components/NavigationMotion";
import { useWelcomeWorkspace } from "./WelcomeWorkspace";
import GuidedDataset from "./GuidedDataset";
import Dropdown from "@/components/Dropdown";
import pickerStyles from "./CasePicker.module.css";
import StageActions from "./StageActions";
import DatasetButtonReview, { type DatasetButtonLayout } from "./DatasetButtonReview";
import { nextCaseId } from "@/lib/dataset-fields";
import type { TutorialDataset } from "@/lib/uti-tutorial";
import type { DatasetCase } from "@/lib/dataset-import";
import { datasetSelection, emptyDatasetDrafts, type DatasetDraftState } from "@/lib/dataset-draft-state";
import { createDatasetDraftSaver, type DraftSaveStatus } from "@/lib/dataset-draft-saver";
import type { StepParams } from "@/lib/caseset/routes";
import styles from "./StageActions.module.css";
import { OutdatedTag } from "./ui";
import type { DatasetOutdated } from "@/lib/dataset-edit";

export interface WorkspaceCase extends DatasetCase { id: string; hasRubric: boolean; hasResults: boolean; outdated?: DatasetOutdated }
export default function DatasetWorkspace({ example, project, cases, params, sources = [], tutorial }: { example: TutorialDataset; project: string; cases: WorkspaceCase[]; params: StepParams | null; sources?: { filename: string; path: string; processed: boolean }[]; tutorial?: Pick<NonNullable<Parameters<typeof GuidedDataset>[0]>, "animateField" | "onTyping" | "onGenerateRequest" | "onNext" | "savedActions"> }) {
  const [selected, setSelected] = useState(params?.caseId ?? cases[0]?.id ?? "new");
  const query = useSearchParams();
  const requestedCase = query?.get("case") ?? null;
  const requestedCaseRef = useRef(requestedCase);
  requestedCaseRef.current = requestedCase;
  const review = process.env.NODE_ENV === "development" && !tutorial && query?.get("review") === "dataset-actions";
  const [buttonLayout, setButtonLayout] = useState<DatasetButtonLayout>("current");
  const separateIntake = Boolean(review && buttonLayout === "separated");
  const [state, setState] = useState<DatasetDraftState>(emptyDatasetDrafts);
  const [loaded, setLoaded] = useState(Boolean(tutorial));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<DraftSaveStatus>({ state: "saved" });
  const currentState = useRef(state);
  const saver = useRef<ReturnType<typeof createDatasetDraftSaver> | null>(null);
  const navigate = useMotionNavigation();
  const { registerBeforeRefresh } = useWelcomeWorkspace();
  useEffect(() => {
    if (!tutorial) return registerBeforeRefresh(() => saver.current?.flush() ?? Promise.resolve(true));
  }, [registerBeforeRefresh, tutorial]);
  const drafts = state.drafts;
  const load = async (signal?: AbortSignal): Promise<void> => {
    setLoadError(null);
    try {
      const response = await fetch(`/api/dataset-drafts?project=${encodeURIComponent(project)}`, { cache: "no-store", signal });
      const value = await response.json() as DatasetDraftState & { error?: string };
      if (!response.ok) throw new Error(value.error);
      currentState.current = value; setState(value);
      setSelected(datasetSelection(cases.map((c) => c.id), value, requestedCaseRef.current));
      saver.current = createDatasetDraftSaver(value.revision, async (snapshot) => {
        const result = await fetch("/api/dataset-drafts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, state: snapshot }) });
        const saved = await result.json() as DatasetDraftState & { error?: string };
        if (!result.ok) throw new Error(saved.error);
        return saved.revision;
      }, setStatus);
      setLoaded(true);
    } catch (caught) { if (!signal?.aborted) setLoadError((caught as Error).message); }
  };
  useEffect(() => {
    if (tutorial) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [project, tutorial]);
  const persist = (next: DatasetDraftState): void => {
    currentState.current = next; setState(next);
    if (!tutorial) saver.current?.enqueue(next);
  };
  const select = (key: string): void => {
    setSelected(key);
    persist({ ...currentState.current, selected: key });
  };
  useEffect(() => {
    if (tutorial || !loaded || !requestedCase || !cases.some((c) => c.id === requestedCase)) return;
    setSelected(requestedCase);
    if (currentState.current.selected !== requestedCase) persist({ ...currentState.current, selected: requestedCase });
  }, [loaded, requestedCase, cases, tutorial]);
  useEffect(() => {
    if (tutorial) return;
    const leave = (event: BeforeUnloadEvent): void => {
      if (saver.current?.pending()) { event.preventDefault(); event.returnValue = ""; }
    };
    const follow = (event: MouseEvent): void => {
      if (!saver.current?.pending() || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest("a[href]") as HTMLAnchorElement | null : null;
      if (!link || link.target && link.target !== "_self" || link.hasAttribute("download")) return;
      const url = new URL(link.href);
      if (url.origin !== window.location.origin || url.pathname === window.location.pathname && url.search === window.location.search) return;
      event.preventDefault(); event.stopImmediatePropagation();
      void saver.current.flush().then((saved) => { if (saved) navigate(url.pathname + url.search + url.hash); });
    };
    window.addEventListener("beforeunload", leave);
    document.addEventListener("click", follow, true);
    return () => { window.removeEventListener("beforeunload", leave); document.removeEventListener("click", follow, true); };
  }, [navigate, tutorial]);
  const current = cases.find((c) => c.id === selected);
  const draftId = nextCaseId([...cases.map((c) => c.id), ...Object.values(drafts).flatMap((draft) => draft.id ? [draft.id] : [])]);
  const selectedParams: StepParams | undefined = current ? { caseId: current.id, version: params?.caseId === current.id ? params.version : null, itemId: params?.caseId === current.id ? params.itemId : current.id, model: params?.model ?? null, trial: params?.trial ?? 1 } : undefined;
  const initial = drafts[selected] ?? current ?? { id: draftId, task: "", solutions: [""], errors: "" };
  const fields = (value: DatasetCase): string => JSON.stringify([value.task, value.solutions.filter((solution) => solution.trim()), value.errors]);
  const edited = Boolean(current && drafts[selected] && fields(drafts[selected]) !== fields(current));
  const entries = [
    ...cases.map((c) => ({ id: c.id, label: c.id.replace(/^Case(\d{3,})$/, "Case-$1") })),
    { id: "new", label: "New case draft" },
    ...Object.keys(drafts).filter((key) => key !== "new" && !cases.some((c) => c.id === key)).map((key) => ({ id: key, label: key.startsWith("edit:") ? `New version of ${key.slice(5)}` : `Draft ${drafts[key].id?.replace(/^Case(\d{3,})$/, "Case-$1")}` })),
  ];
  const move = (offset: number): void => select(entries[(entries.findIndex((entry) => entry.id === selected) + offset + entries.length) % entries.length].id);
  const controls = <><div className="flex items-center gap-2">
    <button aria-label="Previous item" title="Previous item" className={`${pickerStyles.arrow} ${pickerStyles.previous}`} type="button" onClick={() => move(-1)}>
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="m15 6-6 6 6 6" /></svg>
    </button>
    <Dropdown aria-label="Dataset entry" className="w-28 max-w-full shrink-0 rounded-md border border-mc-line bg-mc-surface-2 px-2 py-1 text-[13.5px] text-mc-ink" title={entries.find((entry) => entry.id === selected)?.label} value={selected} onChange={(event) => select(event.target.value)}>
      {entries.map((entry) => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
    </Dropdown>
    <button aria-label="Next item" title="Next item" className={`${pickerStyles.arrow} ${pickerStyles.next}`} type="button" onClick={() => move(1)}>
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="m9 6 6 6-6 6" /></svg>
    </button>
  </div><div className={styles.actions}><button type="button" onClick={() => { const key = `new:${draftId}`; persist({ ...currentState.current, selected: key, drafts: { ...drafts, [key]: { id: draftId, task: "", solutions: [""], errors: "" } } }); setSelected(key); }}>Add Case</button></div>{!tutorial && <span className="text-xs text-mc-muted" role="status">{status.state === "saving" ? "Saving draft…" : status.state === "error" ? "Draft not saved" : "Draft saved"}</span>}</>;
  if (!loaded) return <div className="text-sm text-mc-muted">{loadError ? <><p role="alert">{loadError}</p><button className="rounded-md border border-mc-line px-3 py-2" type="button" onClick={() => void load()}>Retry Load</button></> : <p role="status">Loading project drafts…</p>}</div>;
  return <>{review && <DatasetButtonReview onChange={setButtonLayout} />}{status.state === "error" && <p role="alert" className="mb-3 text-sm text-mc-bad">Draft not saved: {status.error} <button className="rounded-md border border-mc-line px-2 py-1" type="button" onClick={() => void saver.current?.flush()}>Retry Save</button></p>}{current && <DatasetNotes current={current} edited={edited} />}<GuidedDataset nextParams={selectedParams} separateIntake={separateIntake} example={example} key={selected} project={tutorial ? undefined : project} initialCase={initial} prepared={Boolean(tutorial)} editableSavedCase={Boolean(current) && !tutorial} originalCase={state.bases[selected] ?? current} onBeforeGenerate={tutorial ? undefined : () => saver.current!.flush()} onCaseSaved={(value) => persist({ ...currentState.current, drafts: { ...currentState.current.drafts, [selected]: value }, bases: { ...currentState.current.bases, [selected]: value } })} controls={controls} onDraftChange={(value) => {
    if (JSON.stringify(currentState.current.drafts[selected]) === JSON.stringify(value)) return;
    persist({ ...currentState.current, selected, drafts: { ...currentState.current.drafts, [selected]: value }, bases: current && !currentState.current.bases[selected] ? { ...currentState.current.bases, [selected]: current } : currentState.current.bases });
  }} savedActions={current?.hasResults && !edited ? <StageActions step="cases" project={project} params={selectedParams} caseIds={cases.map((c) => c.id)} missingCases={cases.filter((c) => !c.hasRubric).map((c) => c.id)} /> : undefined} sources={sources} {...tutorial} /></>;
}

// Edits keep existing rubrics and responses; they are tagged out of date rather than replaced or hidden.
function DatasetNotes({ current, edited }: { current: WorkspaceCase; edited: boolean }) {
  const { rubric, responses } = current.outdated ?? { rubric: null, responses: 0 };
  if (!rubric && !responses && !(edited && current.hasResults)) return null;
  return <ul className="mb-3 list-none space-y-1.5 p-0 text-sm" aria-label="Case changes">
    {rubric && <li className="flex flex-wrap items-center gap-2"><OutdatedTag output="rubric" reason={rubric} /><span>The rubric was made from the earlier {rubric === "task" ? "Task" : "Solution"}. Generate a new rubric.</span></li>}
    {responses > 0 && <li className="flex flex-wrap items-center gap-2"><OutdatedTag output="response" reason="task" /><span>{responses} model {responses === 1 ? "response was" : "responses were"} collected for the earlier Task.</span></li>}
    {edited && current.hasResults && <li className="text-mc-muted">This case already has a rubric or responses. Saving keeps them and tags them out of date until they are regenerated.</li>}
  </ul>;
}

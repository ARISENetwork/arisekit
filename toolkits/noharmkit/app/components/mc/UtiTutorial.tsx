"use client";

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useMotionNavigation } from "@/components/NavigationMotion";
import Link from "@/components/MotionLink";
import { createPortal } from "react-dom";
import DatasetWorkspace from "@/components/mc/DatasetWorkspace";
import StageActionPlacement from "./StageActionPlacement";
import TutorialEditorReturnGuide from "./TutorialEditorReturnGuide";
import actionStyles from "./StageActions.module.css";
import WelcomeWorkspace from "@/components/mc/WelcomeWorkspace";
import type { NavData } from "@/components/mc/nav";
import { TUTORIAL_CASE, TUTORIAL_STAGES, tutorialHref, type TutorialDataset } from "@/lib/uti-tutorial";
import { STEP_KEYS } from "@/lib/caseset/steps";
import styles from "./UtiTutorial.module.css";
import workspaceStyles from "./WelcomeWorkspace.module.css";

const DATASET_GUIDANCE = [
  { heading: "Welcome to the NOHARMKit interface", text: "We’ll walk you through the workflow.", target: null },
  { heading: "Your place in the pipeline", text: "The sidebar shows your current step and links to Dashboard, Quick Reference, and Framework. We’ll start with adding your dataset.", target: '[aria-label="Pipeline sidebar"]' },
  { heading: "Provide a task", text: "This is a benchmark case, question, or task to pose to the LLM. Here we'll use a simple example of asking for clinical management steps on a UTI case.", target: '#example-input' },
  { heading: "Provide a solution", text: "A solution is an appropriate expert response or answer. If there are multiple appropriate solutions, you can incorporate them into a single solution, or add multiple solutions.", target: '#example-reference' },
  { heading: "Add an alternative solution", text: "Add another appropriate response as a separate solution.", target: '[data-tutorial-add-solution]' },
  { heading: "Describe possible errors", text: "Describe possible errors and their severity. You don't need to be exhaustive, but listing a few options, including both commissions and omissions, improves the rubric generation.", target: '#example-errors' },
  { heading: "Your first case", text: "Click Generate rubric.", target: '[data-generate-rubric]' },
  { heading: "This step is already complete", text: "You don’t need to paste this prompt into your coding agent for the walkthrough. We’ve already generated the example rubric. Click Next to review it.", target: null },
] as const;

const RUBRIC_GUIDANCE = [
  { heading: "The Rubrics page", text: "Now we’re in the next step: Rubrics. Here you can see the input case and the generated rubric." },
  { heading: "Explore the rubric", text: "Open the rubric editor to explore the full rubric and make changes." },
] as const;

const RESPONSE_GUIDANCE = [
  { heading: "The Responses page", text: "This page lets you run and see responses from different models. To test a range of models easily, we recommend OpenRouter. Here we've already tested hypothetical Models A, B, and C." },
  { heading: "Choose a model", text: "Click the Model dropdown and choose Model B or Model C." },
  { heading: "Read the response", text: "The output shows the selected model’s response to the same task. Try the other models, then click Next to review autograding." },
] as const;

export default function UtiTutorial({ example, index, nav, children, editor = false, editorContent, exportRows }: { example: TutorialDataset; index: number; nav: NavData; children?: ReactNode; editor?: boolean; editorContent: ReactNode; exportRows: Record<string, unknown>[] }): ReactNode {
  const navigate = useMotionNavigation();
  const editorDialog = useRef<HTMLDialogElement>(null);
  const [editorOpened, setEditorOpened] = useState(editor);
  const [editorMounted, setEditorMounted] = useState(editor);
  const [editorVisited, setEditorVisited] = useState(editor);
  const openEditor = (): void => { setGuidance(false); setEditorMounted(true); setEditorOpened(true); setEditorVisited(true); };
  const closeEditor = (): void => { setEditorOpened(false); setGuidance(true); };
  useEffect(() => {
    if (editorOpened) editorDialog.current?.showModal();
    else if (editorDialog.current?.open) editorDialog.current.close();
  }, [editorOpened]);
  const root = useRef<HTMLDivElement>(null);
  const guidanceAnchor = useRef<HTMLDivElement>(null);
  const [guidanceHost, setGuidanceHost] = useState<HTMLDivElement | null>(null);
  const [guidance, setGuidance] = useState(true);
  const [responseStep, setResponseStep] = useState(0);
  const [rubricStep, setRubricStep] = useState(0);
  const [outputStep, setOutputStep] = useState(0);
  const exploringResponses = index === 2 && responseStep > 0 && guidance;
  const choosingModel = index === 2 && responseStep === 1 && guidance;
  const [datasetStep, setDatasetStep] = useState(0);
  const [handoffDialog, setHandoffDialog] = useState<HTMLDialogElement | null>(null);
  useLayoutEffect(() => {
    const host = document.createElement("div");
    guidanceAnchor.current!.appendChild(host);
    setGuidanceHost(host);
    return () => host.remove();
  }, []);
  useLayoutEffect(() => {
    if (!guidanceHost) return;
    // Keep the portal target stable as the native dialog enters the top layer.
    const modal = index === 0 && handoffDialog ? handoffDialog : null;
    if (modal) modal.dataset.tutorialGuidance = "true";
    (modal ?? guidanceAnchor.current!).appendChild(guidanceHost);
    return () => { if (modal) delete modal.dataset.tutorialGuidance; };
  }, [guidanceHost, handoffDialog, index]);
  const [typing, setTyping] = useState(false);
  const [alternativeAdded, setAlternativeAdded] = useState(false);
  const [spotlight, setSpotlight] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const dialog = useRef<HTMLElement>(null);
  const dialogContent = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState({ left: 24, top: 80, width: 448, height: 260, side: "none", pointer: 24 });
  const dataset = index === 0;
  const field = datasetStep === 2 ? "task" : datasetStep === 3 ? "solution" : datasetStep === 4 && alternativeAdded ? "alternative" : datasetStep === 5 ? "errors" : undefined;
  const targetSelector = dataset ? datasetStep === 4 && alternativeAdded ? '#example-solution-1' : DATASET_GUIDANCE[datasetStep].target : index === 1 && !editorVisited ? rubricStep === 0 ? null : "[data-tutorial-open-editor]" : index === 1 ? '[aria-label="Rubric preview"]' : index === 2 && responseStep === 0 || index >= 3 && outputStep === 0 ? null : index === 2 && responseStep === 1 ? "#mc-model" : index === 2 ? "section:has([data-model-response])" : index === 5 ? '[aria-label="Pipeline sidebar"] a[href="/noharm/dashboard"]' : '[data-step-output]';
  const stage = TUTORIAL_STAGES[index];
  const go = (next: number): void => { const query = new URLSearchParams(window.location.search); query.set("step", TUTORIAL_STAGES[next].key); navigate(`/noharm/tutorial?${query}`); };
  const next = (): void => {
    if (index >= 3 && outputStep === 0) { setOutputStep(1); return; }
    if (index === 2 && responseStep < RESPONSE_GUIDANCE.length - 1) { setResponseStep((previous) => previous + 1); return; }
    if (index === 1 && !editorVisited) {
      if (rubricStep < RUBRIC_GUIDANCE.length - 1) setRubricStep((previous) => previous + 1);
      else openEditor();
      return;
    }
    if (dataset && datasetStep === 4 && !alternativeAdded) { setAlternativeAdded(true); return; }
    if (dataset && datasetStep === DATASET_GUIDANCE.length - 2) { root.current?.querySelector<HTMLFormElement>('section[aria-label="Dataset draft"] form')?.requestSubmit(); return; }
    if (dataset && datasetStep < DATASET_GUIDANCE.length - 1) { setDatasetStep((previous) => previous + 1); setGuidance(true); }
    else if (index === 0) go(1);
    else if (index < TUTORIAL_STAGES.length - 1) go(index + 1);
  };
  useEffect(() => {
    if (!dataset || datasetStep !== DATASET_GUIDANCE.length - 1) { setHandoffDialog(null); return; }
    const modal = root.current?.querySelector<HTMLDialogElement>('dialog[aria-labelledby="dataset-dialog-title"]') ?? null;
    setHandoffDialog(modal);
    const close = (): void => setHandoffDialog(null);
    modal?.addEventListener("close", close);
    return () => modal?.removeEventListener("close", close);
  }, [dataset, datasetStep]);
  useEffect(() => { setGuidance(!editor); setEditorOpened(editor); setEditorVisited(editor); setDatasetStep(0); setResponseStep(0); setRubricStep(0); setOutputStep(0); setTyping(false); setAlternativeAdded(false); root.current?.querySelector("main")?.scrollTo({ top: 0 }); }, [index, editor]);
  useEffect(() => {
    if (!guidance) return;
    const previous = document.activeElement as HTMLElement | null;
    const container = root.current;
    const focus = (): void => {
      if (choosingModel) container?.querySelector<HTMLButtonElement>('#mc-model')?.focus();
      else dialog.current?.querySelector<HTMLButtonElement>('button')?.focus();
    };
    const afterDialogExit = (event: TransitionEvent): void => {
      if (event.propertyName === "overlay" && event.target instanceof HTMLDialogElement && !event.target.open) focus();
    };
    focus();
    container?.addEventListener("transitionend", afterDialogExit);
    return () => {
      container?.removeEventListener("transitionend", afterDialogExit);
      if (previous?.isConnected && previous !== document.body && !previous.closest('[role="dialog"]')) previous.focus();
      else document.querySelector<HTMLButtonElement>('[data-guidance-trigger]')?.focus();
    };
  }, [guidance, choosingModel, handoffDialog, guidanceHost, index, datasetStep, rubricStep, responseStep, outputStep, editorVisited]);
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const update = (): void => {
      let target: Element | null = null;
      if (guidance) {
        const selector = targetSelector;
        target = selector ? element.querySelector(selector) ?? document.querySelector(selector) : null;
      }
      const rect = target?.getBoundingClientRect();
      const main = element.querySelector("main");
      const preview = main?.getBoundingClientRect();
      if (guidance && rect && preview && target && (rect.top < preview.top || rect.bottom > preview.bottom)) target.scrollIntoView({ block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
      if (guidance) {
        const left = rect ? Math.max(4, rect.left - 4) : 0;
        const top = rect ? Math.max(4, rect.top - 4) : 0;
        const bottom = window.innerHeight - 4;
        setSpotlight(rect ? { left, top, width: Math.min(rect.right + 4, window.innerWidth - 4) - left, height: Math.min(rect.bottom + 4, bottom) - top } : null);
        const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
        const width = Math.min((dataset ? [28, 25, 24, 26, 26, 26, 24, 27][datasetStep] : 27) * rem, window.innerWidth - 32);
        const height = (dialogContent.current?.getBoundingClientRect().height ?? 260) + 2;
        const gap = 12;
        const clamp = (value: number, low: number, high: number): number => Math.max(low, Math.min(value, high));
        let x = (window.innerWidth - width) / 2;
        let y = (window.innerHeight - height) / 2;
        let side = "none";
        if (rect) {
          x = clamp(rect.left, 16, window.innerWidth - width - 16);
          if (index === 2 && responseStep === 1 && rect.right + gap + width <= window.innerWidth - 16) { x = rect.right + gap; y = rect.top; side = "left"; }
          else if (rect.bottom + gap + height <= window.innerHeight - 16) { y = rect.bottom + gap; side = "top"; }
          else if (rect.top - gap - height >= 16) { y = rect.top - gap - height; side = "bottom"; }
          else if (rect.left - gap - width >= 16) { x = rect.left - gap - width; y = rect.top; side = "right"; }
          else if (rect.right + gap + width <= window.innerWidth - 16) { x = rect.right + gap; y = rect.top; side = "left"; }
          else y = rect.top + gap;
        }
        y = clamp(y, 16, window.innerHeight - height - 16);
        const pointer = rect ? side === "left" || side === "right" ? clamp(rect.top + rect.height / 2 - y, 24, height - 24) : clamp(rect.left + rect.width / 2 - x, 24, width - 24) : 24;
        const nextPlacement = { left: x, top: y, width, height, side, pointer };
        setPlacement((previous) => Object.entries(nextPlacement).every(([key, value]) => previous[key as keyof typeof previous] === value) ? previous : nextPlacement);
      }

    };
    update();
    const observer = new MutationObserver((changes) => { if (changes.some((change) => change.type === "childList")) update(); });
    observer.observe(element, { childList: true, subtree: true });
    const resizeObserver = new ResizeObserver(update);
    if (dialogContent.current) resizeObserver.observe(dialogContent.current);
    const observedTarget = targetSelector ? element.querySelector(targetSelector) ?? document.querySelector(targetSelector) : null;
    if (observedTarget) resizeObserver.observe(observedTarget);
    window.addEventListener("resize", update);
    element.addEventListener("scroll", update, true);
    return () => { observer.disconnect(); resizeObserver.disconnect(); window.removeEventListener("resize", update); element.removeEventListener("scroll", update, true); };
  }, [guidance, index, editor, dataset, datasetStep, targetSelector, guidanceHost, handoffDialog]);
  const coach = <aside ref={dialog} className={styles.coach} data-open={guidance} style={{ left: placement.left, top: placement.top, width: placement.width, height: placement.height, "--pointer-offset": `${placement.pointer}px` } as CSSProperties} aria-hidden={!guidance} inert={!guidance} role="dialog" aria-modal={!exploringResponses} aria-labelledby="tutorial-guidance-title" onKeyDown={(event) => {
    if (event.key === "Escape") setGuidance(false);
    if (event.key === "Tab" && !exploringResponses) {
      const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }}>
    <svg className={styles.pointer} data-side={placement.side} aria-hidden="true" viewBox="0 0 18 10"><path d="M0 10 9 1 18 10" /></svg>
    <div ref={dialogContent} className={styles.coachContent}>
    <div className={styles.coachTop}><span>{`Step ${dataset ? datasetStep + 1 : index === 1 ? editorVisited ? 3 : rubricStep + 1 : index === 2 ? responseStep + 1 : outputStep + 1} of ${dataset ? DATASET_GUIDANCE.length : index === 1 ? 3 : index === 2 ? RESPONSE_GUIDANCE.length : 2}` }</span><button type="button" aria-label="Dismiss guidance" onClick={() => setGuidance(false)}>Close</button></div>
    <h2 id="tutorial-guidance-title">{dataset ? DATASET_GUIDANCE[datasetStep].heading : index === 2 ? RESPONSE_GUIDANCE[responseStep].heading : index === 1 && !editorVisited ? RUBRIC_GUIDANCE[rubricStep].heading : index >= 3 && outputStep === 0 ? `The ${stage.title} page` : stage.heading}</h2>
    <p>{dataset ? DATASET_GUIDANCE[datasetStep].text : index === 2 ? RESPONSE_GUIDANCE[responseStep].text : index === 1 && editorVisited ? "You’ve explored the rubric editor. Click Next to see model responses." : index === 1 ? RUBRIC_GUIDANCE[rubricStep].text : index >= 3 && outputStep === 0 ? ["", "", "", "Autograding maps each model response to the rubric. Here you can review the automated judgments, evidence, and omissions.", "Scores summarize the judgments and potential harm. Here you can check coverage and inspect each response’s scores.", "The leaderboard brings the scores together so you can compare responses across models. These prepared examples do not measure model performance."][index] : stage.guidance}</p>
    <div className={styles.coachActions}>{index >= 3 && outputStep > 0 && <button className={styles.help} type="button" onClick={() => setOutputStep(0)}>Back</button>}{dataset && datasetStep > 0 && <button className={styles.help} type="button" disabled={typing} onClick={() => { if (datasetStep === DATASET_GUIDANCE.length - 1) handoffDialog?.querySelector<HTMLButtonElement>("header > div > button")?.click(); setDatasetStep((previous) => previous - 1); }}>Back</button>}{index === 1 && !editorVisited && rubricStep > 0 && <button className={styles.help} type="button" onClick={() => setRubricStep((previous) => previous - 1)}>Back</button>}{index === 2 && responseStep > 0 && <button className={styles.help} type="button" onClick={() => setResponseStep((previous) => previous - 1)}>Back</button>}{(index < 5 || outputStep === 0) && !choosingModel && <button className={workspaceStyles.primaryAction} type="button" disabled={typing} onClick={next}>{dataset && datasetStep === 4 && !alternativeAdded ? "Add alternative solution" : dataset && datasetStep === DATASET_GUIDANCE.length - 2 ? "Generate Rubric" : index === 1 && !editorVisited && rubricStep === RUBRIC_GUIDANCE.length - 1 ? "Open Rubric Editor" : "Next"}</button>}{index === 5 && outputStep === 1 && <button className={workspaceStyles.primaryAction} type="button" onClick={() => navigate("/noharm/dashboard")}>View Dashboard</button>}</div>
    </div>
  </aside>;
  const submitDataset = (): void => { root.current?.querySelector<HTMLFormElement>('section[aria-label="Dataset draft"] form')?.requestSubmit(); };
  const exportResults = (): void => {
    const columns = Object.keys(exportRows[0] ?? {});
    const cell = (value: unknown): string => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = [columns.map(cell).join(","), ...exportRows.map((row) => columns.map((key) => cell(row[key])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "uti-walkthrough-leaderboard.csv"; anchor.click(); URL.revokeObjectURL(url);
  };
  const navigation = <StageActionPlacement><div inert={guidance || editorOpened} className={actionStyles.actions}>
    <button type="button" data-guidance-trigger className={styles.walkthroughTrigger} onClick={() => setGuidance(true)}>Walkthrough</button>
    {index > 0 && <button type="button" onClick={() => go(index - 1)}>Previous</button>}
    {dataset && <button data-generate-rubric className={actionStyles.primary} type="button" disabled={typing} onClick={submitDataset}>Generate Rubric</button>}
    {index >= 2 && index <= 4 && <button className={actionStyles.primary} type="button" onClick={() => setGuidance(true)}>{["", "", "Collect Responses", "Run Autograder", "Compute Scores"][index]}</button>}
    {index === 5 && <button className={actionStyles.primary} type="button" onClick={exportResults}>Export Results</button>}
    {index < 5 && <button type="button" disabled={typing} onClick={() => go(index + 1)}>Next</button>}
    {index === 5 && <Link href="/noharm/welcome?walkthrough=complete">Finish Walkthrough</Link>}
  </div></StageActionPlacement>;
  const content = <div className={styles.page} data-dataset={dataset} data-tutorial-page>{dataset ? <DatasetWorkspace example={example} project="__guided-uti__" cases={[{ id: TUTORIAL_CASE, task: "", solutions: [""], errors: "", hasRubric: false, hasResults: false }]} params={null} tutorial={{ savedActions: navigation, animateField: field, onTyping: setTyping, onGenerateRequest: () => { setDatasetStep(DATASET_GUIDANCE.length - 1); setGuidance(true); }, onNext: () => go(1) }} /> : <>{children}{navigation}</>}</div>;
  return <div className={styles.root} ref={root} onChangeCapture={(event) => { if (choosingModel && (event.target as HTMLElement).getAttribute("aria-label") === "Model") setResponseStep(2); }} onClickCapture={(event) => {
    if ((event.target as HTMLElement).closest("[data-tutorial-open-editor]")) { openEditor(); return; }
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as HTMLElement).closest<HTMLAnchorElement>("a[href]");
    if (!anchor) return;
    const path = new URL(anchor.href).pathname;
    if (path === "/review" || path === "/noharm/review") { event.preventDefault(); event.stopPropagation(); openEditor(); return; }
    if (anchor.closest("dialog") && (path === "/rubrics" || path === "/noharm/rubrics")) { event.preventDefault(); event.stopPropagation(); closeEditor(); return; }
    const href = tutorialHref(anchor.getAttribute("href")!);
    if (href) { event.preventDefault(); event.stopPropagation(); navigate(href); }
  }}><div inert={guidance && !exploringResponses || editorOpened}><WelcomeWorkspace nav={nav} tutorialStep={STEP_KEYS[index]}>{content}</WelcomeWorkspace></div><div ref={guidanceAnchor} />{guidanceHost && createPortal(<><div className={styles.veil} data-open={guidance} data-spotlight={Boolean(spotlight)} data-interactive={exploringResponses} aria-hidden="true" />{spotlight && <div className={styles.spotlight} data-open={guidance} style={spotlight} aria-hidden="true" />}{coach}</>, guidanceHost)}<dialog ref={editorDialog} className={styles.editorDialog} aria-labelledby="tutorial-editor-title" onCancel={(event) => { event.preventDefault(); closeEditor(); }}><header className={styles.editorHeader}><h2 id="tutorial-editor-title">NOHARM Rubric Editor</h2><button className={styles.help} type="button" onClick={closeEditor}>Close Editor</button></header><div className={styles.editorBody}>{editorMounted && editorContent}</div><TutorialEditorReturnGuide opened={editorOpened} onReturn={closeEditor} /></dialog></div>;
}

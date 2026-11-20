"use client";
import { useEffect, useId, useRef, useState } from "react";
import Link from "@/components/MotionLink";
import PromptBox from "./PromptBox";
import { ModelSetupLink, useApiExecution } from "./ApiExecution";
import { generateRubricLabel, type ApiPipelineAction } from "@/lib/api-pipeline-action";
import { useLocalResponseParams } from "./LocalResponses";
import { STEP_KEYS, type StepKey } from "@/lib/caseset/steps";
import { stepHref, type StepParams } from "@/lib/caseset/routes";
import { noharmHref } from "@/lib/noharm-path";
import { TEXT_V2_DRAFT_GUIDANCE } from "@/lib/caseset/prompts";
import styles from "./StageActions.module.css";
import StageActionPlacement from "./StageActionPlacement";
import { useChosenPrompt } from "./ResponsePromptPicker";
import { autogradeLabel, collectLabel, NO_OUTDATED, replaceAutogradingNote, responsesAction, responsesAgentPrompt, responsesProposal, type OutdatedResponses } from "@/lib/response-prompt-picker";
import dialogStyles from "./GuidedDataset.module.css";

export default function StageActions({ step, project, params: initialParams, hidePrimary = false, blocked, missingCases = [], caseIds = [], exportRows, outdated = NO_OUTDATED, stale = NO_OUTDATED }: { step: StepKey; project: string; params?: StepParams; hidePrimary?: boolean; blocked?: string; missingCases?: string[]; caseIds?: string[]; exportRows?: Record<string, unknown>[]; outdated?: OutdatedResponses; stale?: OutdatedResponses }) {
  const params = useLocalResponseParams() ?? initialParams;
  const execution = useApiExecution();
  const api = execution?.mode === "api" && execution.project === project && project !== "__guided-uti__";
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState("current");
  const [selectedCases, setSelectedCases] = useState<string[]>(params?.caseId ? [params.caseId] : []);
  const chosenPrompt = useChosenPrompt();
  const copyTarget = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  const next = STEP_KEYS[STEP_KEYS.indexOf(step) + 1];
  const target = JSON.stringify(project);
  const item = params?.caseId ? ` for item ${JSON.stringify(params.caseId)}` : "";
  const scopeText = scope === "all" ? " for all items" : scope === "missing" ? ` for items ${JSON.stringify(missingCases)}` : scope === "selected" ? ` for items ${JSON.stringify(selectedCases)}` : item;
  const prompts: Record<StepKey, string> = {
    cases: `Use noharm-rubrics for project ${target}. Generate one draft rubric${scopeText}. ${TEXT_V2_DRAFT_GUIDANCE}`,
    rubrics: `Use noharm-rubrics for project ${target}. Generate one draft rubric${item}. ${TEXT_V2_DRAFT_GUIDANCE}`,
    responses: responsesAgentPrompt(`Use noharm-responses for project ${target}. Collect independent responses${item} using the agreed models.`, chosenPrompt, outdated),
    autograding: `Use noharm-autograding for project ${target}. Autograde the stored responses${scope === "all" ? " for all items" : item} using rubric ${JSON.stringify(params?.version)}. Check that every selected case has this rubric label before running. Preserve its stored format and the judge rules pinned for the project.`,
    scores: `Use noharm-scores for project ${target}. Compute scores and check coverage. Preserve each stored rubric format: error severities and bounds for text rubrics, existing scoring for legacy answer tables.`,
    leaderboard: "",
  };
  const action = (): ApiPipelineAction => {
    if (step === "responses") return responsesAction(chosenPrompt, outdated);
    if (step === "autograding") return { stage: "judge", ...(params?.version ? { rubric: params.version } : {}), ...(scope !== "all" && params?.caseId ? { caseIds: [params.caseId] } : {}), ...(stale.count ? { replaceOutdated: true } : {}) };
    if (step === "scores") return { stage: "score" };
    const ids = step === "cases" ? scope === "missing" ? missingCases : scope === "selected" ? selectedCases : scope === "all" ? undefined : params?.caseId ? [params.caseId] : undefined : params?.caseId ? [params.caseId] : undefined;
    return { stage: "generate", ...(ids ? { caseIds: ids } : {}) };
  };
  const label: Record<StepKey, string> = { cases: generateRubricLabel(step === "cases" ? action().caseIds : undefined), rubrics: "Generate Rubric", responses: collectLabel(outdated), autograding: autogradeLabel(stale), scores: "Compute Scores", leaderboard: "Download leaderboard CSV" };
  const availability = execution?.readiness?.[step === "scores" ? "scoring" : "modelCalls"];
  const unavailable = execution?.readinessError ?? (!availability ? "Checking execution availability…" : !availability.available ? availability.reason : null);
  const exportResults = (): void => {
    const rows = exportRows ?? [];
    const columns = Object.keys(rows[0] ?? {});
    const cell = (value: unknown): string => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = [columns.map(cell).join(","), ...rows.map((row) => columns.map((key) => cell(row[key])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = `${project}-leaderboard.csv`; a.click(); URL.revokeObjectURL(url);
  };
  return <><StageActionPlacement><div className={styles.bar}><div className={styles.actions}>
    {!hidePrimary && <button className={styles.primary} type="button" disabled={Boolean(blocked) || Boolean(api && execution.active && step !== "leaderboard")} onClick={step === "leaderboard" ? exportResults : () => setOpen(true)}>{api && execution.active && step !== "leaderboard" ? "Pipeline running…" : label[step]}</button>}
    <Link href={next ? stepHref(next, params ? { case: params.caseId, version: params.version, item: params.itemId, model: params.model, trial: params.trial } : {}) : noharmHref("/dashboard")}>{next ? "Next" : "Back to Dashboard"}</Link>
  </div>{blocked && step !== "scores" && step !== "leaderboard" && <p className={styles.note}>{blocked}</p>}</div></StageActionPlacement>
  <dialog className={dialogStyles.dialog} ref={dialog} onCancel={() => setOpen(false)} aria-label={api ? `${label[step]} scope` : "Coding-agent handoff"}><header className={dialogStyles.dialogHeading}><h2>{api ? label[step] : "Paste this into your coding agent"}</h2><div className={dialogStyles.dialogHeaderActions}><span id={copyTarget} /><button type="button" onClick={() => setOpen(false)}>Close</button></div></header>{step === "cases" && <label className={dialogStyles.projectDestination}>Cases to generate<select value={scope} onChange={(event) => setScope(event.target.value)}><option value="current">Current case</option><option value="missing" disabled={!missingCases.length}>Cases without a rubric ({missingCases.length})</option><option value="selected">Selected cases</option><option value="all">All cases</option></select></label>}{step === "autograding" && <label className={dialogStyles.projectDestination}>Cases to autograde<select value={scope} onChange={(event) => setScope(event.target.value)}><option value="current">Current case ({params?.caseId})</option><option value="all">All cases with rubric {params?.version}</option></select></label>}{step === "autograding" && <p>{scope === "all" ? `Every imported case must have rubric ${params?.version}. Missing or incompatible rubrics block the run before model calls. To use different versions, autograde each case separately.` : `Only ${params?.caseId} uses rubric ${params?.version} in this run. Other cases and their judgments are preserved.`}</p>}{step === "cases" && scope === "selected" && <fieldset><legend>Select cases</legend>{caseIds.map((id) => <label key={id} className="block text-sm"><input type="checkbox" checked={selectedCases.includes(id)} onChange={(event) => setSelectedCases((previous) => event.target.checked ? [...previous, id] : previous.filter((value) => value !== id))} /> {id.replace(/^Case(\d{3,})$/, "Case-$1")}</label>)}</fieldset>}{scope === "selected" && !selectedCases.length ? <p>Select at least one case.</p> : api ? <>
    <p className="whitespace-pre-wrap">{step === "cases" || step === "rubrics" || step === "autograding" ? action().caseIds ? `Cases: ${action().caseIds!.join(", ")}.` : "All imported cases." : responsesProposal(chosenPrompt, outdated)}{step === "autograding" && params?.version ? ` Rubric: ${params.version}.` : ""}{step === "autograding" ? replaceAutogradingNote(stale) : ""}</p>
    <p>{step === "scores" ? "Scores are computed deterministically. No model call is needed." : "This action uses your saved API model setup and OpenRouter credits. Completed checkpoints are retained."}</p>
    {execution.configured ? <><div className={styles.actions}><button className={styles.primary} type="button" disabled={execution.active || Boolean(unavailable)} onClick={() => { setOpen(false); void execution.run(action()); }}>{label[step]}</button></div>{unavailable && <p>{unavailable}</p>}</> : <ModelSetupLink className="text-mc-accent underline underline-offset-4">Set up API models</ModelSetupLink>}
  </> : <PromptBox prompt={prompts[step]} lead="Copy this prompt and paste it into your coding agent. Come back once your coding agent finishes." copyLabel="Copy prompt" copyButtonTarget={copyTarget} miniCopy />}</dialog></>;
}

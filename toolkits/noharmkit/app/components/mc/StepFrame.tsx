import { projectTrials, trialNumbers } from "@/lib/caseset/trials";
import type { ReactNode } from "react";

import CasePicker from "@/components/mc/CasePicker";
import EvidenceLinker from "@/components/mc/EvidenceLinker";
import LocalResponses, { LocalResponseSlot, type LocalResponsesData } from "@/components/mc/LocalResponses";
import { ResponsePromptProvider } from "@/components/mc/ResponsePromptPicker";
import RoutePicker from "@/components/mc/RoutePicker";
import RubricReviewProgress from "@/components/mc/RubricReviewProgress";
import StageActions from "@/components/mc/StageActions";
import { outdatedResponses, staleAutograding } from "@/lib/response-prompt-picker";
import StepHeading from "@/components/mc/StepHeading";
import { Card, Chips } from "@/components/mc/ui";
import type { Benchmark, CaseStatus, ResponseStatus, StepSummary } from "@/lib/caseset/metrics";
import { modelLabel } from "@/lib/caseset/model-label";
import { stepHref } from "@/lib/caseset/routes";
import type { StepParams } from "@/lib/caseset/routes";
import type { StepKey } from "@/lib/caseset/steps";

export interface StepProps { bench: Benchmark; params: StepParams }

// resolveStepParams always returns a case that exists.
export const caseOf = (bench: Benchmark, params: StepParams): CaseStatus => bench.cases.find((c) => c.caseId === params.caseId) ?? bench.cases[0];

export function rowOf(bench: Benchmark, params: StepParams): ResponseStatus | null {
  return caseOf(bench, params).responses.find((r) => r.row.itemId === params.itemId && r.row.model === params.model && r.row.trial === params.trial) ?? null;
}

export function stepSummary(s: StepSummary): ReactNode {
  return (
    <>
      <span className="font-mc-mono">{s.done} / {s.total}</span>
      {s.reviewed !== null && <span>{s.reviewed} of {s.reviewTotal} reviewed</span>}
    </>
  );
}

export function ResponsePicker({ bench, params, step }: StepProps & { step: StepKey }) {
  const c = caseOf(bench, params);
  const models = [...new Set([...c.responses.map((r) => r.row.model), ...bench.models])].sort();
  const trials = [...new Set([
    ...trialNumbers(projectTrials(bench.trials)),
    ...c.responses.filter((r) => r.row.model === params.model && r.row.itemId === params.itemId).map((r) => r.row.trial),
    ...c.missing.filter((m) => m.model === params.model && m.itemId === params.itemId).map((m) => m.trial),
  ])].filter((trial) => Number.isSafeInteger(trial) && trial >= 1).sort((a, b) => a - b);
  const href = (over: Record<string, string | number>): string => stepHref(step, { case: params.caseId, version: params.version, item: params.itemId, model: params.model, trial: params.trial, ...over });
  return (
    <>
      {models.length > 0 && <RoutePicker id="mc-model" label="Model" options={models.map((model) => ({ value: model, label: modelLabel(model, c.page.provenance), href: href({ model, trial: 1 }) }))} value={params.model ?? models[0]} />}
      {c.items.length > 1 && <Chips label="Variant" options={c.items.map((i) => ({ key: i, label: i, href: href({ item: i, trial: 1 }), current: i === params.itemId }))} />}
      {trials.length > 1 && <Chips label="Trial" options={trials.map((t) => ({ key: String(t), label: `Trial ${t}`, href: href({ trial: t }), current: t === params.trial }))} />}
    </>
  );
}

export function StepPanel({ title, note, children, compact = false }: { title: string; note?: ReactNode; children?: ReactNode; compact?: boolean }) {
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-mc-line px-4 py-3">
        <h2 className="m-0 text-sm font-semibold">{title}</h2>
        {note && <span className="ml-auto truncate text-xs text-mc-muted">{note}</span>}
      </div>
      <div className={`flex flex-col px-4 ${compact ? "gap-2 py-3" : "gap-3.5 py-4"}`}>{children}</div>
    </Card>
  );
}

export default function StepFrame({ bench, params, step, picker, headerActions, inputs, inputsNote, inputsBelow, outputs, outputsNote, outputsBelow, inputsTitle = "Input", outputsTitle = "Output", equalColumns = false, inputsAboveOutput = false, localResponses, evidenceLinked = false, children }: StepProps & {
  step: StepKey; picker?: ReactNode; headerActions?: ReactNode; inputs?: ReactNode; inputsNote?: string; inputsBelow?: ReactNode; outputs?: ReactNode; outputsNote?: string; outputsBelow?: ReactNode; inputsTitle?: string; outputsTitle?: string; equalColumns?: boolean; children?: ReactNode;
  localResponses?: LocalResponsesData;
  evidenceLinked?: boolean;
  inputsAboveOutput?: boolean;
}) {
  const current = caseOf(bench, params);
  const table = current.page.tables.find((t) => t.version === params.version && t.status === "pass");
  const selectedResponse = rowOf(bench, params);
  const textV2 = Boolean(current.page.tables.find(t => t.version === params.version)?.textV2);
  const nativeDescription: Partial<Record<StepKey, string>> = {
    rubrics: "Review criteria, main approaches and add-ons with explicit appropriateness and error severity.",
    autograding: "The judge matches each part of the model response to rubric items and notes what is missing.",
    scores: "Scoring computes omission and commission errors from the current judgment.",
  };
  const blocked = step === "responses" && !table ? "Generate and select a rubric first." : step === "autograding" && (!table || !selectedResponse?.row.response) ? "Select a rubric and collect a response first." : step === "scores" && !bench.cases.some((c) => c.responses.some((r) => r.row.judge === "pass")) ? "Run autograding before computing scores." : undefined;
  const ids = bench.cases.map((c) => c.caseId);
  const hrefs = Object.fromEntries(ids.map((id) => [id, stepHref(step, { case: id })]));
  const content = (
    <div className="flex min-h-full flex-1 flex-col">
      <header className={`${step === "responses" ? "mb-3" : "mb-5"} flex flex-wrap items-start gap-3.5`}>
        <StepHeading step={step} description={textV2 ? nativeDescription[step] : undefined} actions={headerActions} />
      </header>
      <CasePicker current={params.caseId} hrefs={hrefs} ids={ids} progress={step === "rubrics" ? <RubricReviewProgress cases={bench.cases} /> : stepSummary(bench.steps[step])}>{picker}</CasePicker>
      {children ?? <div className={`grid grid-cols-1 items-start gap-4 ${equalColumns ? "lg:grid-cols-2" : "lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]"}`}>
        <div className="flex min-w-0 flex-col gap-4">
          {!inputsAboveOutput && <StepPanel note={inputsNote} title={inputsTitle}>{inputs}</StepPanel>}
          {inputsBelow}
        </div>
        <div className="flex min-w-0 flex-col gap-4" data-step-output={step}>
          {inputsAboveOutput && <StepPanel note={inputsNote} title={inputsTitle}>{inputs}</StepPanel>}
          <StepPanel note={localResponses ? <LocalResponseSlot name="note">{outputsNote}</LocalResponseSlot> : outputsNote} title={outputsTitle}>{outputs}</StepPanel>
          {outputsBelow}
        </div>
      </div>}
          {bench.name !== "__guided-uti__" && <StageActions key={`${bench.name}:${params.caseId}:${params.version}`} step={step} project={bench.name} params={params} blocked={blocked} hidePrimary={step === "rubrics" && Boolean(table)} {...(step === "responses" ? { outdated: outdatedResponses(bench.cases) } : step === "autograding" ? { stale: staleAutograding(bench.cases) } : {})} />}
    </div>
  );
  const identity = `${bench.name}:${params.caseId}:${params.itemId}:${params.model}:${params.trial}`;
  const linked = evidenceLinked ? <EvidenceLinker key={identity}>{content}</EvidenceLinker> : content;
  const framed = localResponses ? <LocalResponses key={identity} {...localResponses}>{linked}</LocalResponses> : linked;
  return step === "responses" ? <ResponsePromptProvider>{framed}</ResponsePromptProvider> : framed;
}

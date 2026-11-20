import TextV2RubricEditor from "@/components/TextV2RubricEditor";
import RubricSummary from "@/components/mc/RubricSummary";
import { datasetFields } from "@/lib/dataset-fields";
import AnswerTableEditor from "@/components/AnswerTableEditor";
import ExpertReviewFiles from "@/components/mc/ExpertReviewFiles";
import RubricEditorPopup from "@/components/mc/RubricEditorPopup";
import { ApiStageAction } from "@/components/mc/ApiExecution";
import Reveal from "@/components/mc/Reveal";
import StepFrame, { caseOf } from "@/components/mc/StepFrame";
import type { StepProps } from "@/components/mc/StepFrame";
import { Chips, Field, OutdatedTag, Prose, ReviewTag, Tag } from "@/components/mc/ui";
import { agentPrompt } from "@/lib/caseset/prompts";
import { stepHref } from "@/lib/caseset/routes";
import styles from "./RubricsStep.module.css";
import type { ReactNode } from "react";

export default function RubricsStep({ bench, params, editor }: StepProps & { editor?: ReactNode }) {
  const c = caseOf(bench, params);
  const table = c.page.tables.find((t) => t.version === params.version) ?? null;
  const fields = datasetFields(c.page.source);
  const inputs = (
    <>
      <Field label="Task"><Prose>{fields.task}</Prose></Field>
      <Field label="Solution"><Prose>{fields.solutions.length === 1 ? fields.solutions[0] : fields.solutions.map((solution, at) => `Acceptable solution ${at + 1}:\n${solution}`).join("\n\n")}</Prose></Field>
      {fields.errors && <Field label="Author-provided errors"><Prose>{fields.errors}</Prose></Field>}
    </>
  );
  const picker = c.page.tables.length > 1
    ? <Chips label="Rubric version" options={c.page.tables.map((t) => ({ key: t.version, label: t.version, href: stepHref("rubrics", { case: c.caseId, version: t.version }), current: t.version === table?.version }))} />
    : null;
  let outputs;
  if (!table) {
    outputs = <ApiStageAction project={bench.name} action={{ stage: "generate", caseIds: [c.caseId] }} label="Generate Rubric" apiLead="No rubric yet." lead="No rubric yet. Ask your agent:" prompt={agentPrompt("rubrics", c.caseId, bench.name)} />;
  } else if (table.textV2) {
    outputs = <>
      <RubricEditorPopup key={`${bench.name}:${c.caseId}:${table.version}`} className={styles.openEditor}><main className="bg-[hsl(var(--background))] text-[hsl(var(--foreground))]"><TextV2RubricEditor caseId={c.caseId} source={{ caseset: bench.name, version: table.version }} validationProvenance={{ judge_scoring_source_commit: c.page.provenance.judge_scoring_source_commit }} reviewState={c.versionStates[table.version] ?? "draft"} synthetic={c.page.provenance.synthetic === true} /></main></RubricEditorPopup>
      <div className="flex flex-wrap items-center gap-2 text-xs text-mc-muted">
        {!c.versionStates[table.version] || c.versionStates[table.version] === "draft" ? <Tag tone="plain">Unreviewed</Tag> : <ReviewTag state={c.versionStates[table.version]} />}
        {table.errors.length > 0 ? <Tag tone="bad">Not ready for scoring</Tag> : <Tag tone="reviewed">Passes validation</Tag>}
        {(table.warnings ?? []).length > 0 && <Tag tone="draft">{table.warnings!.length} {table.warnings!.length === 1 ? "warning" : "warnings"}</Tag>}
      </div>
      {table.errors.length > 0 && <ul className="m-0 list-disc pl-5 text-xs text-mc-bad">{table.errors.map((message, index) => <li key={index}>{message}</li>)}</ul>}
      {(table.warnings ?? []).length > 0 && <ul className="m-0 list-disc pl-5 text-xs text-mc-muted">{table.warnings!.map((message, index) => <li key={index}>{message}</li>)}</ul>}
      {c.rubric.unusedReviewed.includes(table.version) && <p className="m-0 text-xs text-mc-muted">Autograding still uses an earlier draft for this item.</p>}
      <RubricSummary record={table.textV2} />
    </>;
  } else if (table.status === "failed" || !table.record) {
    outputs = (
      <>
        <div><Tag tone="bad">Failed validation</Tag></div>
        <ul className="m-0 list-disc space-y-0.5 pl-5 text-sm text-mc-bad">{table.errors.map((e, i) => <li className="break-words" key={i}>{e}</li>)}</ul>
        {table.raw && <Reveal summary={<span className="text-sm font-medium">Raw model output</span>}><pre className="m-0 max-h-96 overflow-auto whitespace-pre-wrap text-xs">{table.raw}</pre></Reveal>}
        <ApiStageAction project={bench.name} action={{ stage: "generate", caseIds: [c.caseId] }} label="Generate Rubric" apiLead="Generate a new draft while preserving the failed attempt." prompt={agentPrompt("fixRubric", c.caseId, bench.name)} />
      </>
    );
  } else {
    const record = table.record;
    outputs = (
      <>
        {bench.name !== "__guided-uti__" && <RubricEditorPopup key={`${bench.name}:${c.caseId}:${table.version}`} className={styles.openEditor}><main className="bg-[hsl(var(--background))] text-[hsl(var(--foreground))] [color-scheme:light]"><AnswerTableEditor caseId={c.caseId} source={{ caseset: bench.name, version: table.version }} reviewState={c.versionStates[table.version] ?? "draft"} synthetic={c.page.provenance.synthetic === true} /></main></RubricEditorPopup>}
        {editor}
        {bench.name === "__guided-uti__" && !editor && <button data-tutorial-open-editor className={styles.openEditor} type="button">Open Rubric Editor</button>}
        {c.rubric.unusedReviewed.includes(table.version) && <p className="m-0 text-xs text-mc-muted">Autograding still uses an earlier draft for this item.</p>}
        {c.rubric.basedOnOlder.includes(table.version) && <p className="m-0 text-xs text-mc-muted">Based on an older draft of {table.basedOn?.version}.</p>}
        <div aria-label="Rubric preview" className={styles.preview}>
          <div className="flex flex-wrap items-center gap-3 text-xs text-mc-muted">
            <span>{record.decisions.length} Decisions</span>
            <span>{record.decisions.reduce((total, decision) => total + decision.recommendations.length, 0)} Options</span>
            <ReviewTag state={c.versionStates[table.version] ?? "draft"} />
          </div>
          <ol className="m-0 mt-3 list-none p-0">
            {record.decisions.slice(0, 4).map((decision) => (
              <li className="flex items-start gap-3 border-t border-mc-line py-3" key={decision.id}>
                <span className="min-w-0 flex-1 text-[13.5px] font-medium"><Prose inline>{decision.question}</Prose></span>
                <span className="shrink-0 pt-0.5 text-xs text-mc-muted">{decision.recommendations.length} {decision.recommendations.length === 1 ? "option" : "options"}</span>
              </li>
            ))}
          </ol>
          {record.decisions.length > 4 && <p className="m-0 mt-1 text-xs text-mc-muted">{record.decisions.length - 4} more decisions in the full editor</p>}

        </div>
      </>
    );
  }
  if (table?.outdated) outputs = <><div><OutdatedTag output="rubric" reason={table.outdated} /></div>{outputs}</>;
  const model = table?.provenance?.model;
  return (
    <StepFrame
      bench={bench}
      inputs={inputs}
      outputs={outputs}
      outputsTitle={table?.textV2 ? "Rubric" : undefined}
      outputsNote={typeof model === "string" ? `${table!.version}, drafted by ${model}` : undefined}
      headerActions={table && table.status !== "failed" && bench.name !== "__guided-uti__" ? <ExpertReviewFiles project={bench.name} caseId={c.caseId} version={table.version} /> : undefined}
      params={params}
      picker={picker}
      step="rubrics"
    />
  );
}

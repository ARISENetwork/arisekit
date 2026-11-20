"use client";

import type { ReactElement } from "react";
import Link from "@/components/MotionLink";
import { ApiStageAction, useApiExecution } from "./ApiExecution";
import { pipelineSourceId } from "@/lib/api-pipeline-action";
import { uploadedDatasetHandoff } from "@/lib/dataset-import";
import type { DatasetDraftState } from "@/lib/dataset-draft-state";
import { noharmHref } from "@/lib/noharm-path";

export default function PendingDataset({ project, drafts, draftPath, sources }: {
  project: string;
  drafts: DatasetDraftState;
  draftPath: string;
  sources: { filename: string; path: string; processed: boolean }[];
}): ReactElement {
  const execution = useApiExecution();
  const api = execution?.mode === "api" && execution.project === project;
  const uploads = sources.filter((source) => !source.processed);
  const entries = Object.entries(drafts.drafts).filter(([, draft]) => draft.task.trim() || draft.solutions.some((solution) => solution.trim()) || draft.errors.trim());
  const ready = entries.filter(([, draft]) => draft.task.trim() && draft.solutions[0]?.trim());
  const incomplete = entries.length - ready.length;
  const pending = uploads.length > 0 || entries.length > 0;
  return <div className="flex flex-col gap-4">
    <div>
      <h2 className="m-0 text-base font-semibold">{pending ? "Dataset awaiting import" : "No cases imported"}</h2>
      <p className="mb-0 mt-1 text-sm text-mc-muted">{pending ? "Your dataset is saved, but no cases have been imported yet." : "Add a Task and Solution in Dataset to get started."}</p>
    </div>
    {uploads.length > 0 ? <>
      <p className="m-0 text-sm text-mc-muted">{api ? "Choose the source to import and generate draft rubrics. Every case in that source will be processed." : "Copy the prompt for the source you want to process into your coding agent. When it finishes, click Refresh."}</p>
      {uploads.map((source) => <ApiStageAction project={project} action={{ stage: "generate", sourceId: api ? pipelineSourceId(source.path) : source.path }} label="Import and generate rubrics" key={source.path} lead={source.filename} apiLead={source.filename} prompt={uploadedDatasetHandoff(project, source.path)} copyLabel="Copy Prompt" />)}
      {entries.length > 0 && <p className="m-0 text-sm text-mc-muted">Your saved drafts are also available in Dataset. Process an uploaded source once; it may already contain those drafts.</p>}
    </> : <>
      {ready.length > 0 && <p className="m-0 text-sm text-mc-muted">{api ? "Choose a saved draft to import and generate its rubric." : "Copy a saved draft’s prompt into your coding agent. When it finishes importing the case and generating its rubric, click Refresh."}</p>}
      {ready.map(([key, draft]) => <ApiStageAction project={project} action={{ stage: "generate", draftKey: key }} label="Import and generate rubric" key={key} lead={`Saved draft${draft.id ? `: ${draft.id.replace(/^Case(\d{3,})$/, "Case-$1")}` : ""}`} apiLead={`Saved draft${draft.id ? `: ${draft.id.replace(/^Case(\d{3,})$/, "Case-$1")}` : ""}`} copyLabel="Copy Prompt" prompt={`Use noharm-import-cases and noharm-rubrics for project ${JSON.stringify(project)}. Read the saved dataset draft at drafts[${JSON.stringify(key)}] in ${JSON.stringify(draftPath)}. Import only that draft and generate its rubric. Preserve its Task, nonempty Solutions, Errors, ID, and source provenance. Do not import other drafts or replace existing cases.`} />)}
      {incomplete > 0 && <p className="m-0 text-sm text-mc-muted">{incomplete === 1 ? "A saved draft still needs" : `${incomplete} saved drafts still need`} a Task and Solution before import. Finish {incomplete === 1 ? "it" : "them"} in Dataset.</p>}
    </>}
    <Link className="self-start text-sm font-medium text-mc-accent underline underline-offset-4" href={noharmHref("/dataset")}>Return to Dataset</Link>
  </div>;
}

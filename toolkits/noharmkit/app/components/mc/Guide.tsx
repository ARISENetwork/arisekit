"use client";

import { useState } from "react";
import Link from "@/components/MotionLink";
import DataPrivacyNotice from "@/components/mc/DataPrivacyNotice";
import PromptBox from "@/components/mc/PromptBox";
import ReviewDisclosure from "@/components/ReviewDisclosure";
import { STEP_NAMES, STEP_NUMBERS } from "@/components/mc/nav";
import { stepHref } from "@/lib/caseset/routes";
import { noharmHref } from "@/lib/noharm-path";
import { STEP_KEYS, type StepKey } from "@/lib/caseset/steps";

const STAGES = {
  cases: { skill: "noharm-import-cases", output: "Task + Solution + Errors", action: "Enter a Task and Solution in Dataset, or use Import dataset to upload a CSV or JSON file. Add acceptable alternatives and possible Errors, then copy the handoff prompt into your coding agent.", details: "Supply the input and reference. Pre-rated criteria are optional; keep your source wording intact.", request: "import my supplied dataset" },
  rubrics: { skill: "noharm-rubrics", output: "Decisions + Options", action: "A rubric turns your Solution and supplied Errors into Decisions and Options. Open the rubric editor from the Output card to review and edit the draft without leaving NOHARMKit.", details: "Unless another route is agreed, rubric generation uses the receiving coding agent's subscription: Codex in Codex, or Claude in Claude Code, without a harm-rating committee. Validation checks structure, not clinical validity. Saving in the editor creates a separate reviewed copy; choose that version for autograding.", request: "draft rubrics for my imported items and help me review them" },
  responses: { skill: "noharm-responses", output: "Model responses", action: "Choose models in the Models to test checklist, then use Copy model selection to give the plan to your agent. Collect Responses opens a separate prompt to run the agreed models. Models see the Task without the Solution or Errors.", details: "Collect one response per case, model, and declared trial. The default is one trial. Agree on the complete model list, route, trial count, and spend before collection. Changing the trial count after collection starts requires a new project/run.", request: "collect responses using the agreed models and declared trials" },
  autograding: { skill: "noharm-autograding", output: "Rubric mappings", action: "The judge compares each stored model response with your chosen rubric and maps it to Decisions and Options. Confirm the rubric version and judge model, then inspect the mappings and failures.", details: "The default judge is GPT-6.1 Sol on OpenRouter with high reasoning effort. Confirm the rubric version, route, and spend before running. Autograding covers the project's stored responses across declared trials. Existing judgments are preserved; changed rubrics or rejudging require a fresh project/run. For interrupted direct OpenAI runs, verified resume can run only missing jobs with unchanged inputs and configuration.", request: "grade the stored responses; confirm the rubric version and judge model with me" },
  scores: { skill: "noharm-scores", output: "Adequacy + harm", action: "Scores are calculated deterministically from the stored judgments. Review Recall, Precision, F1, harm, and coverage as separate measures.", details: "Recall, Precision, and F1 describe adequacy. Harm is reported separately. Missing or failed responses are not zero scores.", request: "compute scores and check coverage" },
  leaderboard: { skill: null, output: "Model comparison", action: "The leaderboard ranks models by Mean F1 across their available scored responses, including partial and unverified results. Compare adequacy and harm alongside coverage and review status.", details: "The leaderboard reads stored scores, with no separate model call. Partial and unverified results receive ranks with their limitations shown; models without scores remain visible without a rank. Ranks may change as coverage increases. A rank or model average does not remove draft or provisional status.", request: "" },
} as const;

function Arrow({ className = "" }: { className?: string }) {
  return <svg aria-hidden="true" className={`h-5 w-5 shrink-0 text-mc-faint ${className}`} fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24"><path d="M3 12h17m-6-6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

export default function Guide({ benchmark }: { benchmark?: string }) {
  const [selected, setSelected] = useState<StepKey>("cases");
  const project = benchmark ?? "my-benchmark";
  const heading = "m-0 text-lg font-semibold tracking-tight";
  const section = "scroll-mt-24 rounded-lg border border-mc-line bg-mc-surface p-5 sm:p-6";
  const resourceButton = "inline-flex min-h-11 items-center justify-center rounded-md bg-mc-accent px-4 py-2 text-sm font-semibold text-mc-surface transition-opacity hover:opacity-85 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent";
  const node = (key: StepKey) => <button aria-controls={`guide-step-${key}`} aria-pressed={selected === key} className={`flex w-full min-w-0 items-center gap-2 rounded-md border px-3 py-3 text-left transition-colors motion-reduce:transition-none ${selected === key ? "border-mc-accent bg-mc-accent-bg text-mc-accent" : "border-mc-line-strong bg-mc-surface hover:border-mc-accent"}`} key={key} onClick={() => setSelected(key)} type="button">
    <span className="font-mc-mono text-xs">{STEP_NUMBERS[key]}</span>
    <span className="min-w-0"><span className="block text-sm font-semibold">{STEP_NAMES[key]}</span><span className="mt-0.5 block text-xs text-mc-muted">{STAGES[key].output}</span></span>
  </button>;
  const checkpoints: Record<StepKey, { supply: string; result: string; check: string }> = {
    cases: { supply: "A Task, one or more acceptable Solutions, and optional Errors with harm levels.", result: "Your upload is saved in the project's imports folder. Your coding agent processes it into cases and drafts rubrics.", check: "Check that Task, Solution, and Errors match your source. Solutions are acceptable alternatives, not cumulative requirements." },
    rubrics: { supply: "Imported items and any existing criteria or ratings you want the agent to use.", result: "A rubric version with Decisions, appropriate and inappropriate Options, and validation results.", check: "Use Open Rubric Editor on the Output card. Check Decisions, Options, appropriateness, and harm levels; save, then close the editor. Choose the saved version before autograding." },
    responses: { supply: "Use the checklist and Copy model selection, or give your agent the full model list. OpenRouter supports testing models from multiple organizations.", result: "One stored response for each expected case, model, and declared trial.", check: "Check missing and failed responses. Decide whether to retry them before comparing models." },
    autograding: { supply: "Stored model responses, the rubric version to use, and your chosen judge model.", result: "Mappings from each model response to rubric Options, with quoted evidence.", check: "Inspect a complete and an incomplete model response. Investigate failed or out-of-date mappings before scoring." },
    scores: { supply: "The stored judgments for the intended rubric version. This step needs no model call.", result: "Recall, Precision, F1, and harm for each scored model response, with coverage information.", check: "Trace unexpected scores back to the model response and mapping. Missing model responses are not zero scores." },
    leaderboard: { supply: "Scores already stored in this project. There is no separate generation step.", result: "A model comparison across the project's items.", check: "Check coverage, harm, and review status alongside F1. A draft comparison is not a clinically validated result." },
  };

  return <div className="space-y-5 text-sm leading-relaxed">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="m-0 text-[28px] font-semibold tracking-[-0.035em]">Quick Reference</h1><p className="m-0 mt-1 text-mc-muted">From your dataset to a model leaderboard.</p></div>
    </header>
    <section aria-labelledby="guide-intro" className={`${section} grid gap-5 lg:grid-cols-[minmax(0,1fr)_400px]`} id="welcome">
      <div>
        <h2 className={heading} id="guide-intro">Welcome to NOHARM<span className="font-normal">Kit</span></h2>
        <p className="mb-0 mt-2 text-mc-muted">Build severity-weighted AI benchmarks from your own data, using the NOHARM framework. This kit is currently streamlined for a single-turn benchmark, but you can adapt the framework to any multi-turn, multimodal, or agentic evaluation.</p>
        <p className="mb-0 mt-2 text-mc-muted">Create your project and prepare your dataset here. Copy each step's prompt into Codex or Claude Code to run the pipeline, then return here to inspect and review the results. No agent connection is required.</p>
      </div>
      <div className="flex flex-col items-start justify-center gap-3 rounded-lg bg-mc-accent-bg p-4">
        <h3 className="m-0 text-base font-semibold">NOHARM framework</h3>
        <p className="m-0 text-xs text-mc-muted">Review the core principles before building your benchmark.</p>
        <div className="grid w-full grid-cols-2 gap-2"><Link className={resourceButton} href={noharmHref("/framework")}>Read the Framework</Link><Link className={resourceButton} href={noharmHref("/tutorial")}>View Tutorial</Link></div>
      </div>
    </section>
    <DataPrivacyNotice />
    <section aria-labelledby="guide-pipeline-overview" className={section} id="pipeline-overview">
      <h2 className={heading} id="guide-pipeline-overview">Pipeline Overview</h2>
      <ol className="mb-0 mt-4 grid list-none grid-cols-2 gap-4 p-0 sm:grid-cols-3 xl:grid-cols-6">
        {([
          ["cases", "Enter cases or upload your dataset."],
          ["rubrics", "Draft and review Decisions and Options."],
          ["responses", "Collect model responses from selected models."],
          ["autograding", "Map model responses to the chosen rubric."],
          ["scores", "Compute adequacy and harm."],
          ["leaderboard", "Compare models across items."],
        ] as const).map(([key, detail]) => <li className="min-w-0" key={key}>
          <div className="flex items-center gap-2"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-mc-accent-bg text-xs font-semibold text-mc-accent">{STEP_NUMBERS[key]}</span><h3 className="m-0 text-sm font-semibold">{STEP_NAMES[key]}</h3></div>
          <p className="mb-0 mt-2 text-xs text-mc-muted">{detail}</p>
        </li>)}
      </ol>
    </section>
    <section className={section} id="start">
      <h2 className={heading}>Your first benchmark</h2>
      <ol className="my-4 grid list-none gap-4 p-0 sm:grid-cols-3">{[["1", "Create a project", "Choose New project and name your benchmark."], ["2", "Add your dataset", "Enter Task, Solution, and Errors, or use Import dataset."], ["3", "Generate and review", "Copy the handoff prompt into your coding agent, then return to Rubrics."]].map(([number, title, detail]) => <li className="flex items-start gap-3" key={number}><span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-mc-accent-bg text-xs font-semibold text-mc-accent">{number}</span><div><h3 className="m-0 text-sm font-semibold">{title}</h3><p className="mb-0 mt-1 text-xs text-mc-muted">{detail}</p></div></li>)}</ol>
      <div className="border-t border-mc-line pt-4">
        <Link className={resourceButton} href={`${noharmHref("/welcome")}?mode=new`}>Create a New Project</Link><p className="mb-0 mt-2 text-xs text-mc-muted">Stage buttons open prompts for you to copy. They do not run model calls. After your agent finishes, reload the page to see its output, then use Next to move to the next stage.</p>
      </div>
      <ReviewDisclosure title="Setup and naming details" expanded>
        <ul className="m-0 list-disc space-y-1 pl-5 text-mc-muted"><li>Open your agent in this repository. The skills ship with the kit; start a new session if they are missing.</li><li>Use 1-64 lowercase letters, digits, or hyphens, starting with a letter or digit.</li><li>Choose model routes and authorize paid calls before generation, responses, or autograding.</li><li>Copying a prompt does not run it. Browser selection does not select a project for your agent; the prompts name it explicitly.</li></ul>
      </ReviewDisclosure>
      <ReviewDisclosure title="First launch and troubleshooting"><ul className="m-0 list-disc space-y-2 pl-5 text-mc-muted"><li>If you have not launched the app yet, follow First launch in the repository README. It includes the setup prompt.</li><li>If a skill is missing, start a new agent session in the whole repository folder, the one containing README.md, tools, and app.</li><li>If your project or output is missing, refresh the app and check the selected project. Ask your agent to confirm it wrote to the project named in the prompt.</li><li>If a step fails, keep its output and ask the agent to inspect it. Use the continuation prompt below to find the next missing, failed, or stale step.</li></ul></ReviewDisclosure>
    </section>
    <ReviewDisclosure title="Pipeline prompts and review details"><div className="space-y-5">
    <section className={section} id="pipeline">
      <h2 className={heading}>Pipeline</h2>
      <p className="mb-0 mt-2 text-mc-muted">For your own project, select each step to see what to supply, what the agent produces, and how to check it. Generation, model responses, and autograding may need provider setup and paid calls; agree on the models and run scope with your agent first.</p>
      {!benchmark && <p className="mb-0 mt-3 text-mc-muted">Create and select your own project before running these prompts. Until then, replace <code>my-benchmark</code> with your chosen project name.</p>}
      <figure className="m-0 mt-5">
        <div aria-label="Six pipeline steps, from Dataset to Leaderboard" className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          {STEP_KEYS.map((key) => <div className="min-w-0" key={key}>{node(key)}</div>)}
        </div>
        <figcaption className="mt-3 text-xs text-mc-muted">Rubrics and model responses meet in autograding. Scores and the leaderboard use those stored judgments.</figcaption>
      </figure>
      <div className="mt-5 border-t border-mc-line pt-4">
        {STEP_KEYS.map((key) => {
          const stage = STAGES[key];
          const active = selected === key;
          return <div aria-hidden={!active} className={`grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none ${active ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`} id={`guide-step-${key}`} inert={!active ? true : undefined} key={key}>
            <div className="min-h-0 overflow-hidden"><div className="pb-1">
              <div className="flex items-baseline justify-between gap-3"><h3 className="m-0 text-base font-semibold">{STEP_NAMES[key]}</h3><Link className="shrink-0 text-xs text-mc-accent underline-offset-4 hover:underline" href={stepHref(key)}>Open {STEP_NAMES[key]}</Link></div>
              <p className="mb-3 mt-1 text-mc-muted">{stage.action}</p>
              <dl className="mb-4 mt-0 grid gap-4 lg:grid-cols-3">{[["You supply", checkpoints[key].supply], ["Expected output", checkpoints[key].result], ["Before continuing", checkpoints[key].check]].map(([label, text]) => <div key={label}><dt className="font-semibold">{label}</dt><dd className="m-0 mt-1 text-mc-muted">{text}</dd></div>)}</dl>
              {stage.skill && <PromptBox lead={`Prompt for ${project}:`} prompt={`Use ${stage.skill} for project ${JSON.stringify(project)}. ${stage.request[0].toUpperCase()}${stage.request.slice(1)}.`} />}
              {key === "cases" ? <ReviewDisclosure title="Dataset format and case names"><div id="cases" className="scroll-mt-24"><p className="mt-0 text-mc-muted">Upload a CSV or JSON file with Task, Solution, and Errors fields. Task and Solution must be nonempty; Errors are optional but recommended.</p><p className="text-mc-muted">For CSV, put multiple acceptable solutions in one Solution field, separated by <code>SOLUTION:</code>. JSON can use an array of solutions:</p><pre className="m-0 overflow-x-auto rounded-md bg-mc-surface-2 p-3 font-mc-mono text-xs leading-6"><code>{JSON.stringify([{ Task: "Your task", Solution: ["An acceptable solution", "Another acceptable solution"], Errors: "Possible errors and their potential severity" }], null, 2)}</code></pre><p className="mt-2 text-mc-muted">Import dataset saves the original file in your project's imports folder. Paste its handoff prompt into your coding agent to process it and generate rubrics. Supplied Errors and harm levels remain author-provided criteria.</p><p className="mb-0 mt-2 text-mc-muted">Cases without supplied IDs receive generic names such as Case-001 and Case-002. Their stored IDs are <code>Case001</code> and <code>Case002</code>. Supplied IDs are preserved; incompatible IDs need an agreed mapping. Stored IDs cannot contain hyphens or path separators, or start with <code>Ex</code>.</p><p className="mb-0 mt-2 text-mc-muted">For direct agent imports, the legacy JSON keys remain <code>presentation</code> for Task and <code>recommendations</code> for Solution. Both must be nonempty strings.</p></div></ReviewDisclosure> : <ReviewDisclosure title="Step details"><p className="m-0 text-mc-muted">{stage.details}</p></ReviewDisclosure>}
            </div></div>
          </div>;
        })}
      </div>
    </section>
    <section className={section} id="results">
      <h2 className={heading}>Results and review</h2>
      <p className="mb-0 mt-2 text-mc-muted">Adequacy and harm describe different parts of model performance. Read them alongside coverage and review status to understand what the results support.</p>
      <dl className="my-4 grid gap-4 sm:grid-cols-3"><div><dt className="font-semibold">Adequacy</dt><dd className="m-0 mt-1 text-mc-muted">Recall, Precision, and F1</dd></div><div><dt className="font-semibold">Safety</dt><dd className="m-0 mt-1 text-mc-muted">Harm, reported separately</dd></div><div><dt className="font-semibold">Evidence</dt><dd className="m-0 mt-1 text-mc-muted">Coverage and review status</dd></div></dl>
      <div className="border-t border-mc-line pt-4"><h3 className="m-0 text-sm font-semibold">After a rubric edit</h3><ol aria-label="Rubric edit rerun sequence" className="m-0 mt-2 flex list-none flex-wrap items-center gap-2 p-0 text-mc-muted"><li>Save reviewed copy</li><li aria-hidden="true"><Arrow /></li><li>Prepare fresh project/run</li><li aria-hidden="true"><Arrow /></li><li>Autograde intended rubric</li><li aria-hidden="true"><Arrow /></li><li>Recompute scores</li></ol></div>
      <ReviewDisclosure title="Review status and coverage"><ul className="m-0 list-disc space-y-1 pl-5 text-mc-muted"><li>LLM draft means model-produced. Validation is not clinical review.</li><li>Provisional means the evidence has limits; an average does not remove them.</li><li>Missing or failed responses are not zero scores. Check coverage before comparing models.</li><li>Saving a reviewed rubric does not update existing judgments. Preserve earlier outputs and use a fresh project/run for rejudging. Verified resume for an interrupted direct OpenAI run can fill missing jobs only; it does not replace failed judgments or accept changed rubrics.</li><li>A completed pipeline run and a completed review are separate.</li></ul></ReviewDisclosure>
    </section>
    </div></ReviewDisclosure>
    <section className={section} id="continue"><h2 className={heading}>Continuing a project</h2><PromptBox lead="Continue with:" prompt={`Use noharm for project ${JSON.stringify(project)}. Inspect the stored outputs and help me run the next pipeline step.`} /></section>
  </div>;
}

import type { ReactNode } from "react";

import { ApiModeContent, ApiStageAction } from "@/components/mc/ApiExecution";
import StepFrame, { caseOf, ResponsePicker, rowOf } from "@/components/mc/StepFrame";
import type { StepProps } from "@/components/mc/StepFrame";
import { KIND, LEVEL, outcomeText } from "@/components/mc/labels";
import { fmt, LimitTags, Prose, ReviewTag } from "@/components/mc/ui";
import type { ResponseStatus } from "@/lib/caseset/metrics";
import { agentPrompt } from "@/lib/caseset/prompts";
import { isTextV2Selection, TextV2ScoresStep } from "@/components/mc/TextV2Results";

// Every state without a score says why and, when the agent can fix it, what to ask.
function noScore(caseId: string, r: ResponseStatus | null, benchmark: string): ReactNode {
  const say = (text: string): ReactNode => <p className="m-0 text-sm text-mc-muted">{text}</p>;
  switch (r?.row.judge) {
    case undefined:
    case "no response": return say("No model response to score.");
    case "not run": return <>{say("Autograding has not run for this model response.")}<ApiStageAction project={benchmark} action={{ stage: "judge" }} label="Run Autograder" prompt={agentPrompt("autograding", caseId, benchmark)} /></>;
    case "failed": return <>{say("Autograding failed for this model response.")}<ApiStageAction project={benchmark} action={{ stage: "judge" }} label="Run Autograder" prompt={agentPrompt("fixAutograding", caseId, benchmark)} /></>;
    case "stale": return <>{say("The rubric, model response, or input changed after autograding.")}<ApiStageAction project={benchmark} action={{ stage: "judge" }} label="Run Autograder" prompt={agentPrompt("autograding", caseId, benchmark)} /></>;
    case "unverified": return <>{say("Autograding inputs were not recorded. Rerun autograding before scoring.")}<ApiStageAction project={benchmark} action={{ stage: "judge" }} label="Run Autograder" prompt={agentPrompt("autograding", caseId, benchmark)} /></>;
    case "pass": return <>{say(r.row.scoreCheck === "mismatch" ? "The score was computed from another autograding and is hidden." : "No score yet.")}<ApiStageAction project={benchmark} action={{ stage: "score" }} label="Compute Scores" prompt={agentPrompt("scores", undefined, benchmark)} /></>;
  }
}

export default function ScoresStep({ bench, params }: StepProps) {
  if (isTextV2Selection({ bench, params })) return <TextV2ScoresStep bench={bench} params={params} />;
  const c = caseOf(bench, params);
  const r = rowOf(bench, params);
  const s = r?.row.scored ?? null;
  const rubric = r?.row.record?.rubric;
  const table = rubric ? c.page.tables.find((t) => t.version === rubric) ?? null : null;
  const question = (id: string): string => table?.record?.decisions.find((d) => d.id === id)?.question ?? "";
  const inputs = s
    ? (
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="text-left text-xs text-mc-muted"><th className="pb-1.5 pr-3 font-semibold">Decision</th><th className="pb-1.5 pr-3 font-semibold">Outcome</th><th className="pb-1.5 text-right font-semibold">Credit</th></tr>
        </thead>
        <tbody>
          {Object.entries(s.decisions).map(([id, d]) => (
            <tr className="border-t border-mc-line align-top" key={id}>
              <td className="py-1.5 pr-3"><span className="font-mc-mono text-xs text-mc-faint">{id}</span> <Prose inline>{question(id)}</Prose></td>
              <td className="py-1.5 pr-3">{outcomeText(d)}</td>
              <td className="py-1.5 text-right font-mc-mono">{d.credit === null ? "-" : d.credit.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
    : <p className="m-0 text-sm text-mc-muted">{r?.row.judge === "pass" ? <ApiModeContent project={bench.name} api="Autograding is ready. Compute Scores calculates the results without a model call.">Autograding is ready. Click Compute scores to get the prompt for your coding agent.</ApiModeContent> : "No current autograding to score."}</p>;
  const events = s ? Object.entries(s.decisions).flatMap(([id, d]) => d.events.map((e, i) => ({ key: `${id}-${i}`, id, ...e }))) : [];
  const outputs = !s
    ? (
      noScore(c.caseId, r, bench.name)
    )
    : (
      <>
        <div className="flex flex-wrap items-center gap-2">
          <ReviewTag state={r?.scoreReviewed ? "reviewed" : "draft"} />
          <LimitTags limits={r?.limits ?? []} />
        </div>
        {r?.row.scoreCheck === "unverified" && <p className="m-0 text-xs text-mc-muted">Computed before scores recorded their inputs, so it cannot be matched to this autograding.</p>}
        <dl className="m-0 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[["Recall", fmt(s.recall)], ["Precision", fmt(s.precision)], ["F1", fmt(s.f1)], ["Worst harm", LEVEL[s.worstHarm] ?? s.worstHarm]].map(([label, value]) => (
            <div className="rounded-md border border-mc-line px-3 py-2" key={label}>
              <dt className="text-xs text-mc-muted">{label}</dt>
              <dd className="m-0 mt-0.5 font-mc-mono text-[17px]">{value}</dd>
            </div>
          ))}
        </dl>
        {events.length > 0 && (
          <ul className="m-0 list-none space-y-1 p-0 text-[13px]">
            {events.map((e) => <li key={e.key}><span className="font-mc-mono text-xs text-mc-faint">{e.id}</span> {KIND[e.kind] ?? e.kind}: {LEVEL[e.severity] ?? e.severity}</li>)}
          </ul>
        )}
      </>
    );
  return (
    <StepFrame
      bench={bench}
      inputs={inputs}
      outputs={outputs}
      outputsNote={s ? `Judge ${s.judgeModel}` : undefined}
      params={params}
      picker={<ResponsePicker bench={bench} params={params} step="scores" />}
      step="scores"
    />
  );
}

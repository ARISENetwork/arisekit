import { ApiModeContent, ApiStageAction } from "@/components/mc/ApiExecution";
import EvidenceMatch from "@/components/mc/EvidenceMatch";
import PipelineMarkdown from "@/components/mc/Markdown";
import Reveal from "@/components/mc/Reveal";
import StepFrame, { caseOf, ResponsePicker, rowOf, StepPanel } from "@/components/mc/StepFrame";
import type { StepProps } from "@/components/mc/StepFrame";
import { LEVEL, outcomeText } from "@/components/mc/labels";
import { fmt, LimitTags, Prose, ReviewTag, ScoreBadge, Tag } from "@/components/mc/ui";
import { highlight, judgeSpans, spanKey } from "@/lib/caseset/lens";
import { agentPrompt } from "@/lib/caseset/prompts";
import { isTutorialProject } from "@/lib/onboarding";
import { isTextV2Selection, TextV2AutogradingStep } from "@/components/mc/TextV2Results";
import { withoutDecisionRefs } from "@/lib/text-v2-eligibility";

export default function AutogradingStep({ bench, params }: StepProps) {
  if (isTextV2Selection({ bench, params })) return <TextV2AutogradingStep bench={bench} params={params} />;
  const c = caseOf(bench, params);
  const r = rowOf(bench, params);
  const record = r?.row.record ?? null;
  const judge = record?.judge ?? null;
  const table = record ? c.page.tables.find((t) => t.version === record.rubric) ?? null : null;
  const labels = new Map<string, string>((table?.record?.decisions ?? []).flatMap((d) => {
    const rows = new Map(d.recommendations.map((rec) => [rec.id, rec.text]));
    const out = judge?.decisions[d.id];
    return [
      ...(out?.recommended ?? []).map((rec, i) => [spanKey.row(d.id, i), `${d.id}: ${d.question}\n${rec.rowId}: ${rows.get(rec.rowId) ?? "Not in this rubric"}`] as const),
      ...(out?.unmatched ?? []).map((_, i) => [spanKey.unmatched(d.id, i), `${d.id}: ${d.question}\nUnmatched statement`] as const),
    ];
  }));
  (judge?.offRubric ?? []).forEach((statement, i) => labels.set(spanKey.offRubric(i), `Off-rubric: ${statement.actionable ? "Actionable" : "Not actionable"}, harm ${LEVEL[statement.harm] ?? statement.harm}`));
  const spans = r?.row.judge === "pass" && judge ? judgeSpans(judge).map((span) => ({ ...span, label: labels.get(span.key) ?? span.label })) : [];
  const missing = highlight(r?.row.response ?? "", spans).missing;
  const missingKeys = new Set(missing.map((span) => span.key));
  const inputs = r?.row.response
    ? <PipelineMarkdown evidenceSpans={spans}>{r.row.response}</PipelineMarkdown>
    : <p className="m-0 text-sm text-mc-muted">No response to autograde.</p>;
  let outputs;
  if (!r || r.row.judge === "no response") {
    outputs = <p className="m-0 text-sm text-mc-muted">Autograding needs a response first.</p>;
  } else if (r.row.judge === "not run") {
    outputs = <ApiStageAction project={bench.name} action={{ stage: "judge", caseIds: [c.caseId], ...(params.version ? { rubric: params.version } : {}) }} label="Run Autograder" apiLead="Not autograded yet." lead="Not autograded yet. Ask your agent:" prompt={agentPrompt("autograding", c.caseId, bench.name)} />;
  } else if (r.row.judge === "failed") {
    outputs = (
      <>
        <div><Tag tone="bad">Failed</Tag></div>
        <ul className="m-0 list-disc space-y-0.5 pl-5 text-sm text-mc-bad">{(record?.errors ?? []).map((e, i) => <li className="break-words" key={i}>{withoutDecisionRefs(e)}</li>)}</ul>
        {record?.raw && <Reveal summary={<span className="text-sm font-medium">Raw autograder output</span>}><pre className="m-0 max-h-96 overflow-auto whitespace-pre-wrap text-xs">{record.raw}</pre></Reveal>}
        <ApiStageAction project={bench.name} action={{ stage: "judge", caseIds: [c.caseId], ...(params.version ? { rubric: params.version } : {}) }} label="Run Autograder" apiLead="Stored failures are preserved. The pipeline checks whether this run can continue." prompt={agentPrompt("fixAutograding", c.caseId, bench.name)} />
      </>
    );
  } else if (r.row.judge === "unverified") {
    outputs = (
      <>
        <div><Tag tone="plain">Unverified inputs</Tag></div>
        <p className="m-0 text-sm text-mc-muted">This autograding did not record all of its inputs. Rerun it to verify the current model response and input.</p>
        {record?.raw && <Reveal summary={<span className="text-sm font-medium">Raw autograder output</span>}><pre className="m-0 max-h-96 overflow-auto whitespace-pre-wrap text-xs">{record.raw}</pre></Reveal>}
        <ApiStageAction project={bench.name} action={{ stage: "judge", caseIds: [c.caseId], ...(params.version ? { rubric: params.version } : {}) }} label="Run Autograder" prompt={agentPrompt("autograding", c.caseId, bench.name)} />
      </>
    );
  } else if (r.row.judge === "stale" || !judge) {
    outputs = (
      <>
        <div><Tag tone="bad">Out of date</Tag></div>
        <p className="m-0 text-sm text-mc-muted">The rubric, model response, or input changed after this autograding.</p>
        <ApiStageAction project={bench.name} action={{ stage: "judge", caseIds: [c.caseId], ...(params.version ? { rubric: params.version } : {}) }} label="Run Autograder" prompt={agentPrompt("autograding", c.caseId, bench.name)} />
      </>
    );
  } else {
    const match = (key: string, text: string, score: number | null, evidence: string) => (
      <EvidenceMatch id={key} key={key} spanKeys={missingKeys.has(key) ? [] : [key]} missing={missingKeys.has(key)} note={missingKeys.has(key)
        ? <><span className="block font-medium">Quoted evidence not found in Input.</span><q>{evidence}</q></>
        : "Matching span highlighted in Input."}>
        <span className="min-w-0"><Prose inline>{text}</Prose>{missingKeys.has(key) && <span className="mt-0.5 block text-xs text-mc-llm">Evidence not found</span>}</span>
        <span aria-label="Rubric score (1-9)"><ScoreBadge value={score} /></span>
      </EvidenceMatch>
    );
    outputs = (
      <>
        <div className="flex flex-wrap items-center gap-2">
          <ReviewTag state={r.autograding ?? "draft"} />
          <LimitTags limits={r.limits} />
          <span className="text-xs text-mc-muted">Against rubric {record?.rubric}</span>
          {r.row.scored && <span className="ml-auto text-xs font-semibold">F1 {fmt(r.row.scored.f1)}{r.row.scoreCheck === "unverified" ? " (unverified)" : ""}</span>}
          {!r.row.scored && <span className="ml-auto text-xs text-mc-muted">Not scored yet</span>}
        </div>
        {c.rubric.unusedReviewed.length > 0 && <ApiStageAction project={bench.name} action={{ stage: "judge", caseIds: [c.caseId], rubric: c.rubric.unusedReviewed[0] }} label="Use reviewed rubric" apiLead="A reviewed rubric exists. Prior judgments are preserved; the pipeline checks whether a fresh run is needed." lead="A reviewed rubric exists but autograding still uses an earlier draft. Ask your agent:" prompt={agentPrompt("useReviewedRubric", c.caseId, bench.name)} />}
        <div className="text-right text-xs text-mc-muted">Rubric score (1-9)</div>
        <div className="space-y-2 text-[13px] leading-5">
          {(table?.record?.decisions ?? []).map((d) => {
            const out = judge.decisions[d.id];
            const result = r.row.scored?.decisions[d.id];
            const rows = new Map(d.recommendations.map((rec) => [rec.id, rec]));
            return <section className="border-t border-mc-line pt-2 first:border-0 first:pt-0" key={d.id}>
              <div className="mb-1 flex items-start gap-3">
                <h3 className="m-0 min-w-0 flex-1 text-[13px] font-semibold"><Prose inline>{d.question}</Prose></h3>
                {result && <span className="shrink-0 text-xs text-mc-muted">{outcomeText(result)}</span>}
              </div>
              {(out?.recommended ?? []).map((rec, i) => match(spanKey.row(d.id, i), rows.get(rec.rowId)?.text ?? rec.rowId, rows.get(rec.rowId)?.score ?? null, rec.evidence))}
              {!out?.recommended?.length && <EvidenceMatch id={`${d.id}:missing`} spanKeys={[]} missing={result?.state !== "inactive"} note={result?.state === "inactive" ? "This decision is not active for the response." : "No supporting span was mapped in Input."}>
                <span className="text-mc-muted">{result?.state === "inactive" ? "Not applicable" : "No recommendation mapped"}</span><ScoreBadge value={null} />
              </EvidenceMatch>}
              {(out?.unmatched ?? []).map((u, i) => match(spanKey.unmatched(d.id, i), "Unmatched statement", null, u.evidence))}
              {out?.contradiction && <div className="mt-1"><Tag tone="bad">Contradiction</Tag></div>}
            </section>;
          })}
        </div>
        {!table?.record && <p className="m-0 text-sm text-mc-muted">The judged rubric is unavailable.</p>}
        {judge.offRubric.length > 0 && <Reveal summary={<span className="text-sm font-medium">Off-rubric statements ({judge.offRubric.length})</span>}>
          <div className="space-y-1 text-[13px]">
            {judge.offRubric.map((o, i) => <EvidenceMatch id={spanKey.offRubric(i)} key={i} spanKeys={missingKeys.has(spanKey.offRubric(i)) ? [] : [spanKey.offRubric(i)]} missing={missingKeys.has(spanKey.offRubric(i))}
              note={missingKeys.has(spanKey.offRubric(i)) ? "Quoted evidence not found in Input." : "Off-rubric span highlighted in Input."}>
              <span className="min-w-0"><Prose inline>{o.evidence}</Prose></span>
              <span className="text-xs text-mc-muted">{o.actionable ? "Actionable" : "Not actionable"}<br />Harm {LEVEL[o.harm] ?? o.harm}</span>
            </EvidenceMatch>)}
          </div>
        </Reveal>}
      </>
    );
  }
  const model = record?.provenance.model;
  return (
    <StepFrame
      bench={bench}
      evidenceLinked={r?.row.judge === "pass"}
      inputs={inputs}
      inputsBelow={<StepPanel title="Autograder">
        <p className="m-0 text-sm">The autograder maps the model response to your rubric and quotes evidence for its matches. <ApiModeContent project={bench.name} api="Choose the autograder in API model setup.">{bench.name === "__guided-uti__" ? "This guided tutorial uses prepared teaching judgments." : isTutorialProject(bench.name) ? "For this tutorial, we can use your coding agent with its existing subscription." : "Choose the autograder model and route with your agent in chat."}</ApiModeContent></p>
        {typeof model === "string" && <p className="m-0 break-words text-sm text-mc-muted">Used for this judgment: {model}</p>}
        <p className="m-0 text-sm text-mc-muted">Review the matches before continuing to Scores.</p>
      </StepPanel>}
      outputs={outputs}
      outputsNote={typeof model === "string" ? `Autograder ${model}` : undefined}
      params={params}
      picker={<ResponsePicker bench={bench} params={params} step="autograding" />}
      step="autograding"
    />
  );
}

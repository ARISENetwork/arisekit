import type { ReactNode } from "react";

import { ApiStageAction } from "@/components/mc/ApiExecution";
import PipelineMarkdown from "@/components/mc/Markdown";
import StepFrame, { caseOf, ResponsePicker, rowOf } from "@/components/mc/StepFrame";
import type { StepProps } from "@/components/mc/StepFrame";
import { Card, Prose, ReviewTag, Tag } from "@/components/mc/ui";
import type { Benchmark } from "@/lib/caseset/metrics";
import { modelBaseLabel, modelLabel, orderResponseSets, promptOf } from "@/lib/caseset/model-label";
import { modelName } from "@/lib/model-names";
import { agentPrompt } from "@/lib/caseset/prompts";
import { expectedTrial, projectTrials } from "@/lib/caseset/trials";
import { trialNumbers } from "@/lib/caseset/trials";
import { stepHref } from "@/lib/caseset/routes";
import Link from "@/components/MotionLink";
import TextV2LeaderboardTable from "@/components/mc/TextV2LeaderboardTable";
import TextV2JudgmentList, { EvidenceScroll, JudgmentEvidenceFrame } from "@/components/mc/TextV2JudgmentList";
import ScoreOutOfDate from "@/components/mc/ScoreOutOfDate";
import JudgmentPanel from "@/components/mc/JudgmentPanel";
import type { ReviewSetup } from "@/components/mc/JudgmentReview";
import { sharedRubric } from "@/lib/caseset/read";
import { isTutorialProject } from "@/lib/onboarding";
import type { JudgmentListData } from "@/components/mc/TextV2JudgmentList";
import { highlight, spanKey } from "@/lib/caseset/lens";
import type { EvidenceSpan } from "@/lib/caseset/lens";
import type { TextV2Case } from "@/lib/rubric-text-v2";
import { applicabilityText } from "@/lib/text-v2-applicability";
import { isPipelineV2 } from "@/lib/text-v2-results";
import { withoutDecisionRefs } from "@/lib/text-v2-eligibility";
import { scoreProvenance, scoreReasons, scoreTiles, severity } from "@/lib/text-v2-score-summary";
import type { ScoreCriterion } from "@/lib/text-v2-score-summary";
import { textV2JudgeProtocol } from "@/lib/text-v2-runtime";
import type { TextV2Judgment, TextV2Score, TextV2Severity } from "@/lib/text-v2-results";

const bounds = (value: [TextV2Severity, TextV2Severity]): string => value[0] === value[1] ? severity(value[0]) : `${severity(value[0])} to ${severity(value[1])}`;
const ROLE = { first: "First approach", addOn: "Add-on", alternative: "Alternative", fallback: "Later care / fallback" };

export function isTextV2Selection({ bench, params }: StepProps): boolean {
  const c = caseOf(bench, params);
  const row = rowOf(bench, params)?.row;
  const version = row?.record?.rubric ?? params.version;
  return Boolean(row?.record?.textV2 || row?.textV2Score || c.page.tables.find(table => table.version === version)?.textV2);
}

function Quote({ text, response, sourceLabel = "model response" }: { text: string; response?: string | null; sourceLabel?: string }): ReactNode {
  if (!text) return <span className="text-mc-muted">No quoted evidence</span>;
  return <><q className="whitespace-pre-wrap break-words">{text}</q>{response !== undefined && !response?.includes(text) && <span className="mt-1 block text-xs text-mc-bad">Quoted evidence not found verbatim in the {sourceLabel}.</span>}</>;
}

export function TextV2JudgmentView({ judgment, rubric, response, caseContext }: { judgment: TextV2Judgment; rubric?: TextV2Case; response?: string | null; caseContext?: string }): ReactNode {
  return <div className="space-y-5 text-[13px] leading-5">
    {Object.entries(judgment.decisions).map(([id, reading]) => {
      const criterion = rubric?.decisions.find(item => item.id === id);
      return <section className="space-y-2 border-t border-mc-line pt-3 first:border-0 first:pt-0" key={id}>
        <h3 className="m-0 font-semibold">{id}: {criterion?.question ?? "Criterion"}</h3>
        <div className="text-mc-muted">{applicabilityText(reading.applicability)}</div>
        {reading.applicability.evidence && <Quote text={reading.applicability.evidence} response={reading.applicability.basis === "case" ? caseContext : response} sourceLabel={reading.applicability.basis === "case" ? "case" : "model response"} />}
        {reading.recommended.map((match, index) => <div className="rounded-md border border-mc-line p-3" key={`${match.rowId}:${index}`}>
          <div className="flex flex-wrap items-center gap-2"><strong>{match.rowId}</strong><Tag tone="plain">{ROLE[match.role]}</Tag><span>{match.completeness === "complete" ? "Complete" : match.completeness === "partial" ? "Partial" : "Absent"}</span><span className="text-mc-muted">{match.actionable ? "Actionable" : "Not actionable"}</span></div>
          <p className="my-2"><Prose inline>{criterion?.recommendations.find(item => item.id === match.rowId)?.text ?? "Item unavailable in the selected rubric"}</Prose></p>
          <Quote text={match.evidence} response={response} />
          {match.missing && <p className="mb-0 mt-2 text-mc-muted">Missing: {match.missing}</p>}
        </div>)}
        {!reading.recommended.length && <p className="m-0 text-mc-muted">No item matches recorded.</p>}
        {reading.contradiction.present && <div className="space-y-1"><Tag tone="bad">Contradiction</Tag>{reading.contradiction.evidence.map((text, index) => <p className="m-0" key={index}><Quote text={text} response={response} /></p>)}</div>}
        {reading.unmatched.map((item, index) => <div className="rounded-md border border-mc-line p-3" key={`unmatched:${index}`}><div className="mb-1 font-medium">Unmatched statement ({item.actionable ? "actionable" : "not actionable"})</div><Quote text={item.evidence} response={response} /></div>)}
      </section>;
    })}
    {judgment.offRubric.length > 0 && <section className="space-y-2 border-t border-mc-line pt-3"><h3 className="m-0 font-semibold">Off-rubric statements</h3>{judgment.offRubric.map((item, index) => <div key={index}><div className="text-mc-muted">{item.actionable ? "Actionable" : "Not actionable"}</div><Quote text={item.evidence} response={response} /></div>)}<p className="m-0 text-xs text-mc-muted">These statements are retained without assigning a rubric error severity.</p></section>}
  </div>;
}

export function TextV2ScoreView({ score, rubric }: { score: TextV2Score; rubric?: TextV2Case }): ReactNode {
  if (!score.decisions) return <ScoreSummary score={score} criteria={rubric?.decisions.map(({ id, question }) => ({ id, question })) ?? []} />;
  return <>
    <dl className="m-0 grid grid-cols-2 gap-3 text-sm">
      <div><dt className="text-mc-muted">Optimal</dt><dd className="m-0 font-semibold">{score.optimal === undefined ? "-" : score.optimal ? "Yes" : "No"}</dd></div>
      <div><dt className="text-mc-muted">Worst error</dt><dd className="m-0 font-semibold">{severity(score.worstError)}</dd></div>
      <div><dt className="text-mc-muted">Worst error bounds</dt><dd className="m-0 font-semibold">{bounds(score.worstErrorBounds)}</dd></div>
    </dl>
    {score.provisional && <p className="m-0 text-sm text-mc-muted">Provisional reading. Error bounds retain the unresolved possibilities.</p>}
    <div className="overflow-x-auto"><table className="w-full border-collapse text-[13px]">
      <thead><tr className="text-left text-xs text-mc-muted">{["Criterion", "Addressed", "Need severity", "Omission", "Commission", "Error", "Error bounds"].map(label => <th className="px-2 py-2 font-semibold first:pl-0" key={label}>{label}</th>)}</tr></thead>
      <tbody>{Object.entries(score.decisions).map(([id, decision]) => <tr className="border-t border-mc-line align-top" key={id}>
        <td className="py-2 pr-2"><strong>{id}</strong><div>{rubric?.decisions.find(item => item.id === id)?.question}</div></td><td className="px-2 py-2">{decision.addressed ? "Yes" : "No"}</td><td className="px-2 py-2">{severity(decision.needSeverity)}</td><td className="px-2 py-2">{severity(decision.omission)}</td><td className="px-2 py-2">{severity(decision.commission)}</td><td className="px-2 py-2">{severity(decision.error)}</td><td className="px-2 py-2">{bounds(decision.errorBounds)}</td>
      </tr>)}</tbody>
    </table></div>
    {Object.entries(score.decisions).some(([, decision]) => decision.events.length > 0) && <div className="space-y-2"><h3 className="m-0 text-sm font-semibold">Error events</h3>{Object.entries(score.decisions).flatMap(([id, decision]) => decision.events.map((event, index) => <p className="m-0 text-[13px]" key={`${id}:${index}`}><strong>{id} {event.rowId}</strong>: {event.kind}, {severity(event.severity)}{event.possible ? " (possible)" : ""}{event.evidence && <><br /><Quote text={event.evidence} /></>}</p>))}</div>}
  </>;
}

// Current-grading scores are medians over rater slots, so they explain themselves from stored totals, not per-criterion rows.
function ScoreSummary({ score, criteria }: { score: TextV2Score; criteria: ScoreCriterion[] }): ReactNode {
  return <div className="flex flex-col gap-4">
    <dl className="m-0 grid grid-cols-2 gap-2.5 xl:grid-cols-4">
      {scoreTiles(score, criteria).map(tile => <div className="flex flex-col gap-0.5 rounded-lg border border-mc-line px-3 py-2.5" key={tile.label}>
        <dt className="text-xs text-mc-muted">{tile.label}</dt>
        <dd className="m-0 text-xl font-semibold tabular-nums">{tile.value}</dd>
        {tile.note && <dd className="m-0 text-xs text-mc-muted">{tile.note}</dd>}
      </div>)}
    </dl>
    <section aria-labelledby="score-reasons">
      <h3 className="m-0 text-[13px] font-semibold" id="score-reasons">What drove this score</h3>
      <ul className="m-0 mt-1 list-none p-0">{scoreReasons(score, criteria).map(reason => <li className="border-t border-mc-line py-2 text-[13.5px] leading-6 first:border-t-0" key={`${reason.criteria?.map(c => c.id).join(",") ?? ""}:${reason.text}`}>
        {reason.criteria?.length === 1 ? <p className="m-0 font-medium"><span className="mr-1.5 text-mc-muted">{reason.criteria[0].id}</span><Prose inline>{reason.criteria[0].question}</Prose></p>
          : reason.criteria && <p className="m-0 font-medium">{reason.criteria.map(c => c.id).join(", ")}</p>}
        <p className="m-0">{reason.text}</p>
      </li>)}</ul>
    </section>
    <p className="m-0 text-xs leading-5 text-mc-muted">{scoreProvenance(score).join(" ")}</p>
  </div>;
}

function unavailable({ bench, params }: StepProps, scoring: boolean): ReactNode {
  const c = caseOf(bench, params);
  const r = rowOf(bench, params)?.row;
  const message = !r?.response ? "A model response is needed first." : r.judge === "failed" ? "Autograding failed." : r.judge === "stale" ? "The rubric, response, input, or judge contract changed after autograding." : r.judge === "unverified" ? "Autograding inputs were not recorded." : scoring && r.judge === "pass" ? r.scoreCheck === "mismatch" ? "The stored score belongs to another autograding and is hidden." : r.scoreCheck === "unverified" ? "Stored score lacks input bindings. Compute Scores again." : "No score yet." : "No current autograding yet.";
  return <><p className="m-0 text-sm text-mc-muted">{message}</p>{r?.record?.errors.length ? <ul className="m-0 list-disc pl-5 text-sm text-mc-bad">{r.record.errors.map((error, index) => <li key={index}>{withoutDecisionRefs(error)}</li>)}</ul> : null}<ApiStageAction project={bench.name} action={{ stage: scoring && r?.judge === "pass" ? "score" : "judge", ...(!(scoring && r?.judge === "pass") ? { caseIds: [c.caseId] } : {}), ...(params.version ? { rubric: params.version } : {}) }} label={scoring && r?.judge === "pass" ? "Compute Scores" : "Run Autograder"} blocked={!r?.response ? "Collect a response first." : undefined} prompt={agentPrompt(scoring && r?.judge === "pass" ? "scores" : "autograding", c.caseId, bench.name)} /></>;
}

export function TextV2AutogradingStep(props: StepProps): ReactNode {
  const { bench, params } = props;
  const c = caseOf(bench, params);
  const r = rowOf(bench, params);
  const response = r?.row.response;
  const judgment = r?.row.judge === "pass" ? r.row.record?.textV2 : undefined;
  const rubric = c.page.tables.find(table => table.version === r?.row.record?.rubric)?.textV2;
  const used = r?.row.record?.rubric;
  const judge = r?.row.record?.provenance.model;
  // An upgraded project always judges each case's shared rubric, so there is no other reviewed rubric to switch to.
  const offerReviewed = c.rubric.unusedReviewed.length > 0 && textV2JudgeProtocol(c.page.provenance) !== "J2.3";
  // Clinician review covers current-grading judgments only; the reviewed reading shows once its review is current.
  const pipelineV2 = r?.row.record?.judge_protocol === "J2.3";
  const reviewed = pipelineV2 && r?.clinicianReview ? r.row.reviewedReading : undefined;
  const spans = judgment && response ? [...textV2Spans(judgment), ...(reviewed ? textV2Spans(reviewed, REVIEWED) : [])] : [];
  const missing = new Set(response ? highlight(response, spans).missing.map(span => span.key) : []);
  const judgeData = judgment ? textV2JudgmentData(judgment, rubric, missing) : null;
  const rubricReviewed = c.versionStates[sharedRubric(c.page.tables, c.page.provenance, c.caseId).label ?? ""] === "reviewed";
  const readOnly = isTutorialProject(bench.name) || bench.name === "demo" && c.page.provenance.synthetic === true;
  const review: ReviewSetup | null = pipelineV2 && judgeData && r && !readOnly ? {
    project: bench.name, model: r.row.model, id: r.row.itemId, trial: r.row.trial, caseHref: stepHref("cases", { case: c.caseId }),
    rubricReviewed,
    criteria: judgeData.criteria.map(criterion => ({ id: criterion.id, question: criterion.question, outsideRubric: criterion.unmatched.some(quote => quote.actionable) })),
    evidenceKeys: Object.fromEntries(spans.filter(span => !missing.has(span.key)).reverse().map(span => [span.evidence, span.key])),
  } : null;
  const judgmentList = judgeData && (pipelineV2 && r ? <JudgmentPanel judge={judgeData} review={review} reviewed={reviewed && r.clinicianReview ? { data: textV2JudgmentData(reviewed, rubric, missing, REVIEWED), reviewer: r.clinicianReview.reviewer, reviewedAt: r.clinicianReview.reviewedAt, rubricReviewed } : null} /> : <TextV2JudgmentList data={judgeData} />);
  return <JudgmentEvidenceFrame><StepFrame {...props} step="autograding" evidenceLinked picker={<ResponsePicker {...props} step="autograding" />} inputs={response ? <><EvidenceScroll /><div data-judgment-response=""><PipelineMarkdown evidenceSpans={spans}>{response}</PipelineMarkdown></div></> : <p className="m-0 text-sm text-mc-muted">No model response to autograde.</p>} outputs={judgment ? <><div className="flex flex-wrap gap-2">{r?.autograding === "reviewed" || r?.autograding === "out of date" ? <ReviewTag state={r.autograding} /> : <Tag tone="plain">Unreviewed</Tag>}</div>{used !== params.version && <p className="m-0 text-sm text-mc-muted">This judgment used rubric {used}; the selected rubric is {params.version ?? "none"}. Changing the selection does not change this stored judgment. <Link className="text-mc-accent underline hover:no-underline" href={stepHref("rubrics", { case: c.caseId, version: used })}>Inspect used rubric</Link></p>}{offerReviewed && <ApiStageAction project={bench.name} action={{ stage: "judge", caseIds: [c.caseId], rubric: c.rubric.unusedReviewed[0] }} label="Use reviewed rubric" apiLead={`Reviewed rubric ${c.rubric.unusedReviewed[0]} is not used by this judgment. Prior results are preserved; the pipeline checks whether a fresh run is needed.`} prompt={agentPrompt("useReviewedRubric", c.caseId, bench.name)} />}{judgmentList}</> : unavailable(props, false)} inputsTitle="Response" inputsNote={r ? modelLabel(r.row.model, c.page.provenance) : undefined} outputsTitle="Judgment" outputsNote={judge ? `Judged by ${modelName(judge) ?? judge}${used ? ` against ${used}` : ""}` : undefined} /></JudgmentEvidenceFrame>;
}

// A reviewed reading's quotes get their own marks, so both readings can link to the response.
const REVIEWED = "reviewed:";

function textV2Spans(judgment: TextV2Judgment, prefix = ""): EvidenceSpan[] {
  return [
    ...Object.entries(judgment.decisions).flatMap(([id, reading]) => [
      ...reading.recommended.map((match, i) => ({ key: prefix + spanKey.row(id, i), label: `${id} ${match.rowId}`, evidence: match.evidence })),
      ...reading.unmatched.map((item, i) => ({ key: prefix + spanKey.unmatched(id, i), label: `${id} unmatched ${i + 1}`, evidence: item.evidence })),
    ]),
    ...judgment.offRubric.map((item, i) => ({ key: prefix + spanKey.offRubric(i), label: `Off-rubric ${i + 1}`, evidence: item.evidence })),
  ];
}

function textV2JudgmentData(judgment: TextV2Judgment, rubric: TextV2Case | undefined, missing: Set<string>, prefix = ""): JudgmentListData {
  const located = (key: string): { key: string; notFound: boolean } => ({ key: prefix + key, notFound: missing.has(prefix + key) });
  return {
    criteria: Object.entries(judgment.decisions).map(([id, reading]) => {
      const criterion = rubric?.decisions.find(item => item.id === id);
      return {
        id,
        question: criterion?.question ?? "Criterion",
        applicability: reading.applicability,
        items: reading.recommended.map((match, i) => ({ ...match, ...located(spanKey.row(id, i)), text: criterion?.recommendations.find(item => item.id === match.rowId)?.text ?? "Item unavailable in the selected rubric" })),
        unmatched: reading.unmatched.map((item, i) => ({ ...item, ...located(spanKey.unmatched(id, i)) })),
        contradiction: reading.contradiction.present ? reading.contradiction.evidence : [],
      };
    }),
    offRubric: judgment.offRubric.map((item, i) => ({ ...item, ...located(spanKey.offRubric(i)) })),
  };
}

export function TextV2ScoresStep(props: StepProps): ReactNode {
  const { bench, params } = props;
  const c = caseOf(bench, params);
  const r = rowOf(bench, params);
  const response = r?.row.response;
  const score = r?.row.judge === "pass" && r.row.scoreCheck === "current" ? r.row.textV2Score : undefined;
  const rubric = c.page.tables.find(table => table.version === r?.row.record?.rubric)?.textV2;
  return <StepFrame {...props} step="scores" picker={<ResponsePicker {...props} step="scores" />} inputs={response ? <PipelineMarkdown>{response}</PipelineMarkdown> : <p className="m-0 text-sm text-mc-muted">No model response to score.</p>} outputs={score ? <>{r?.scoreBehindReview && <ScoreOutOfDate project={bench.name} />}{r?.scoreReviewed ? <ReviewTag state="reviewed" /> : <Tag tone="plain">Unreviewed</Tag>}<TextV2ScoreView score={score} rubric={rubric} /></> : unavailable(props, true)} inputsTitle="Response" inputsNote={r ? modelLabel(r.row.model, c.page.provenance) : undefined} outputsTitle="Score" outputsNote={score?.judgeModel && !isPipelineV2(score) ? `Judge ${score.judgeModel}` : undefined} />;
}

export interface TextV2LeaderboardRow {
  model: string;
  scored: number;
  expected: number;
  optimal: number | null;
  none: number;
  mild: number;
  moderate: number;
  severe: number;
  unresolved: number;
  provisional: number;
  worstErrorLowerBound: TextV2Severity | null;
  worstErrorUpperBound: TextV2Severity | null;
  meanF1: number | null;
  severeReviewReadings: number;
  clinicianReviewed: number;
  scoresBehindReview: number;
  pending: number;
  incomplete: number;
  slotsIncomplete: number;
  moreThanThreeSlots: boolean;
  previousPipeline: boolean;
  prompt: string | null;
  promptSha256: string | null;
}

export function textV2LeaderboardRows(bench: Benchmark): TextV2LeaderboardRow[] {
  const cases = bench.cases.filter(c => c.page.tables.some(table => table.textV2));
  const trials = projectTrials(bench.trials);
  const expected = cases.reduce((total, c) => total + c.items.length * trials, 0);
  const levels: TextV2Severity[] = ["none", "mild", "moderate", "severe"];
  const provenance = bench.cases[0]?.page.provenance ?? {};
  return orderResponseSets(bench.models, provenance).map(model => {
    const prompt = promptOf(model, provenance);
    const scoredResponses = cases.flatMap(c => c.responses.filter(r => r.row.model === model && c.items.includes(r.row.itemId) && expectedTrial(r.row.trial, trials) && r.row.judge === "pass" && r.row.scoreCheck === "current" && r.row.textV2Score));
    const scores = scoredResponses.map(r => r.row.textV2Score!);
    const worstBound = (index: 0 | 1): TextV2Severity | null => scores.length ? scores.reduce<TextV2Severity>((worst, score) => levels.indexOf(score.worstErrorBounds[index]) > levels.indexOf(worst) ? score.worstErrorBounds[index] : worst, "none") : null;
    const current = scores.filter(isPipelineV2);
    const final = current.filter(score => score.final);
    const meanF1 = final.length ? final.reduce((total, score) => total + score.f1!, 0) / final.length : null;
    const previousPipeline = scores.some(score => !isPipelineV2(score));
    return { model, scored: scores.length, expected, optimal: scores.some(score => score.optimal === undefined) ? null : scores.filter(score => score.optimal).length, none: scores.filter(score => score.worstError === "none").length, mild: scores.filter(score => score.worstError === "mild").length, moderate: scores.filter(score => score.worstError === "moderate").length, severe: scores.filter(score => score.worstError === "severe").length, unresolved: scores.filter(score => score.worstError === null).length, provisional: scores.filter(score => score.provisional).length, worstErrorLowerBound: worstBound(0), worstErrorUpperBound: worstBound(1), meanF1: previousPipeline ? null : meanF1, severeReviewReadings: current.filter(score => score.reading === "severe review").length, clinicianReviewed: scoredResponses.filter(r => isPipelineV2(r.row.textV2Score!) && r.row.textV2Score!.reading === "clinician review" && r.scoreReviewed).length, scoresBehindReview: scoredResponses.filter(r => r.scoreBehindReview).length, pending: current.filter(score => score.reading === "judge (severe review pending)").length, incomplete: current.length - final.length, slotsIncomplete: current.filter(score => score.complete === false).length, moreThanThreeSlots: current.some(score => (score.slotCount ?? 0) > 3), previousPipeline, prompt: typeof prompt === "object" && prompt ? prompt.name : null, promptSha256: typeof prompt === "object" && prompt ? prompt.sha256 : null };
  });
}

export interface TextV2ResultDetail {
  caseId: string;
  itemId: string;
  model: string;
  trial: number;
  version: string | null;
  scored: boolean;
  optimal: boolean;
  worstError: TextV2Severity | null;
  provisional: boolean;
  worstErrorUpperBound: TextV2Severity | null;
  f1: number | null;
  pending: boolean;
  status: string;
  criteria: string[];
  href: string;
  action: string;
  judgmentHref?: string;
}

export function textV2ResultDetails(bench: Benchmark): TextV2ResultDetail[] {
  return bench.cases.filter(c => c.page.tables.some(table => table.textV2)).flatMap(c => bench.models.flatMap(model => c.items.flatMap(itemId => trialNumbers(projectTrials(bench.trials)).map(trial => {
    const row = c.responses.find(r => r.row.model === model && r.row.itemId === itemId && r.row.trial === trial)?.row;
    const score = row?.judge === "pass" && row.scoreCheck === "current" ? row.textV2Score : undefined;
    const version = row?.record?.rubric ?? c.page.tables.find(table => table.textV2 && table.status === "pass")?.version ?? null;
    const target = { case: c.caseId, item: itemId, model, trial, version };
    const missing = !row?.response || Boolean(row.responseError);
    const step = missing ? "responses" : row?.judge !== "pass" ? "autograding" : "scores";
    const status = missing ? row?.responseError ? `Response failed: ${row.responseError}` : "Missing response" : row?.judge !== "pass" ? `Autograding: ${row?.judge ?? "not run"}` : !score ? row?.scoreCheck === "mismatch" ? "Score inputs changed" : row?.scoreCheck === "unverified" ? "Unverified score inputs" : "Not scored" : score.worstError === null ? `Unresolved (${bounds(score.worstErrorBounds)})` : `${severity(score.worstError)}${score.provisional ? " (provisional)" : ""}`;
    return { caseId: c.caseId, itemId, model, trial, version, scored: Boolean(score), optimal: score?.optimal === true, worstError: score?.worstError ?? null, provisional: score?.provisional ?? false, worstErrorUpperBound: score?.worstErrorBounds[1] ?? null, f1: score?.f1 ?? null, pending: score?.reading === "judge (severe review pending)", status, criteria: score ? Object.entries(score.decisions ?? {}).filter(([, decision]) => decision.error === null || decision.provisional).map(([id]) => id) : [], href: stepHref(step, target), action: missing ? "Inspect response" : step === "autograding" ? "Inspect autograding" : score ? "Inspect score" : "Compute scores", ...(score ? { judgmentHref: stepHref("autograding", target) } : {}) };
  }))));
}

export function TextV2Leaderboard({ bench }: { bench: Benchmark }): ReactNode {
  const rows = textV2LeaderboardRows(bench);
  const details = textV2ResultDetails(bench);
  const first = details.find(detail => !detail.scored);
  const scored = rows.reduce((total, row) => total + row.scored, 0);
  const empty = scored ? null : <div className="flex flex-col items-start gap-2 px-5 pb-4"><p className="m-0 text-sm text-mc-muted">No current scores yet.</p>{first ? <Link className="text-sm text-mc-accent underline underline-offset-4 hover:no-underline" href={first.href}>{first.action}: {first.caseId}, trial {first.trial}</Link> : <Link className="text-sm text-mc-accent underline underline-offset-4 hover:no-underline" href={stepHref("responses")}>Collect responses</Link>}</div>;
  const provenance = bench.cases[0]?.page.provenance ?? {};
  return <TextV2LeaderboardTable project={bench.name} rows={rows} details={details} empty={empty} labels={Object.fromEntries(rows.map(row => [row.model, modelLabel(row.model, provenance)]))} baseLabels={Object.fromEntries(rows.map(row => [row.model, modelBaseLabel(row.model, provenance)]))} />;
}

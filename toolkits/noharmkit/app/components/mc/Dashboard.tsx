import Link from "@/components/MotionLink";

import Customize from "@/components/mc/Customize";
import RubricReviewProgress from "@/components/mc/RubricReviewProgress";
import { DOT_CLASS, STEP_NAMES } from "@/components/mc/nav";
import { Card } from "@/components/mc/ui";
import { rubricReviewProgress, type AttentionKey, type Benchmark, type StepSummary } from "@/lib/caseset/metrics";
import { stepHref } from "@/lib/caseset/routes";
import { noharmHref } from "@/lib/noharm-path";
import { STEP_KEYS } from "@/lib/caseset/steps";

const ATTENTION_DOT: Record<AttentionKey, string> = {
  failedRubrics: "bg-mc-dot-bad", failedAutograding: "bg-mc-dot-bad", missingAnswers: "bg-mc-dot-bad", unexpectedAnswers: "bg-mc-dot-bad", reviewOutOfDate: "bg-mc-dot-bad",
  staleAutograding: "bg-mc-dot-model", unverifiedAutograding: "bg-mc-dot-model", disagreements: "bg-mc-dot-none", provisionalScores: "bg-mc-dot-draft", mixedRubrics: "bg-mc-dot-draft", unusedReview: "bg-mc-dot-draft",
};

const STEP_GUIDE = {
  cases: "Import inputs and references",
  rubrics: "Draft and review rubrics",
  responses: "Collect model responses",
  autograding: "Map responses to rubrics",
  scores: "Compute scores and harm",
  leaderboard: "Compare models across items",
};

function Meter({ s, bench }: { s: StepSummary; bench: Benchmark }) {
  const pct = (n: number): string => `${s.total ? (n / s.total) * 100 : 0}%`;
  const reviewed = s.reviewed ?? 0;
  // The rubric bar counts saved reviewed rubrics, like the line under it; the issues list flags results that still
  // use an earlier rubric.
  const rubrics = s.key === "rubrics" ? rubricReviewProgress(bench.cases) : null;
  const segments: Array<[number, string]> = rubrics
    ? [[rubrics.savedReviewed, "bg-mc-dot-reviewed"], [rubrics.savedTotal - rubrics.savedReviewed, "bg-mc-dot-draft"]]
    : s.reviewed === null
      ? [[s.done, DOT_CLASS[s.dot]]]
      : [[reviewed, "bg-mc-dot-reviewed"], [s.done - reviewed, "bg-mc-dot-draft"]];
  return (
    <Link className="flex flex-col gap-2 px-4 pb-4 pt-3.5 text-mc-ink no-underline transition-colors hover:bg-mc-surface-2" href={bench.name ? stepHref(s.key) : noharmHref("/welcome#new-project")}>
      <span className="flex items-center gap-2 text-[13px] font-medium text-mc-muted">
        <span aria-hidden="true" className={`h-[7px] w-[7px] rounded-full ${DOT_CLASS[s.dot]}`} />
        {STEP_NAMES[s.key]}
      </span>
      <span className="min-h-[3lh] text-xs leading-normal text-mc-muted">{STEP_GUIDE[s.key]}</span>
      <span className="font-mc-mono text-[22px] tracking-tight">{s.done}<small className="text-[13px] tracking-normal text-mc-faint"> / {s.total}</small></span>
      <span className="min-h-[2lh] text-xs leading-normal text-mc-muted">{{ cases: "items imported", rubrics: "items with rubrics", responses: "responses collected", autograding: "responses autograded", scores: "responses scored", leaderboard: "models with scores" }[s.key]}</span>
      <span className="flex h-1 overflow-hidden rounded bg-mc-surface-2">
        {segments.map(([n, color], i) => <i className={`block h-full ${color}`} key={i} style={{ width: pct(n) }} />)}
      </span>
      {s.key === "rubrics" ? <RubricReviewProgress cases={bench.cases} compact /> : <span className="font-mc-mono text-xs text-mc-muted">{s.reviewed === null || s.reviewTotal === 0 ? " " : `${reviewed} of ${s.reviewTotal} reviewed`}</span>}
    </Link>
  );
}

function Row({ href, label, detail, count, dot }: { href: string; label: string; detail: string; count: number; dot: string }) {
  return (
    <Link className="-mx-2 grid grid-cols-[10px_minmax(0,1fr)_auto] items-center gap-3 rounded-md px-2 py-2.5 text-mc-ink no-underline transition-colors hover:bg-mc-surface-2" href={href}>
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dot}`} />
      <span className="min-w-0">
        <b className="block text-[13.5px] font-semibold">{label}</b>
        <span className="text-xs text-mc-muted">{detail}</span>
      </span>
      <span className="font-mc-mono text-[13px]">{count}<span aria-hidden="true" className="ml-2 text-mc-faint">&rsaquo;</span></span>
    </Link>
  );
}

export default function Dashboard({ bench, projectsRoot, exampleProject }: { bench: Benchmark; projectsRoot?: string; exampleProject?: string }) {
  const hasPendingWork = bench.attention.length > 0 || bench.awaiting.rubrics > 0;
  return (
    <>
      <h1 className="m-0 text-[28px] font-semibold tracking-[-0.035em]">Dashboard</h1>
      <Card className="mt-5 overflow-hidden">
        <h2 className="m-0 px-5 pt-5 text-[15px] font-semibold">Pipeline</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
          {STEP_KEYS.map((key) => <Meter bench={bench} key={key} s={bench.steps[key]} />)}
        </div>
      </Card>
      {hasPendingWork && <Card className="mt-4 p-5">
        <h2 className="m-0 mb-2 text-[15px] font-semibold">Review and issues</h2>
        {bench.awaiting.rubrics > 0 && <Row count={bench.awaiting.rubrics} detail="Selected or previously used rubrics not yet reviewed" dot="bg-mc-dot-draft" href={stepHref("rubrics")} label="Rubric review" />}
        {bench.attention.map((a) => <Row count={a.count} detail={a.detail} dot={ATTENTION_DOT[a.key]} href={stepHref(a.step, a.target ?? {})} key={a.key} label={a.label} />)}
      </Card>}
      <Customize benchmark={bench.name || undefined} projectsRoot={projectsRoot} textV2={bench.cases.some(c => c.page.tables.some(t => t.textV2))} />
    </>
  );
}

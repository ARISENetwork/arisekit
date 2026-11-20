import Link from "@/components/MotionLink";
import PipelineMarkdown from "@/components/mc/Markdown";
import type { ReactNode } from "react";

import { LEVEL } from "@/components/mc/labels";
import type { F1Summary } from "@/lib/caseset/metrics";
import type { ReviewState } from "@/lib/caseset/reviews";

// Explicit typography keeps native buttons and links consistent over the global font reset.
export const BUTTON = "inline-flex items-center rounded-md border border-mc-line-strong bg-mc-surface px-2.5 py-1 text-xs! font-medium! leading-4! text-mc-ink no-underline transition-colors hover:border-mc-ink";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-lg border border-mc-line bg-mc-surface shadow-mc ${className}`}>{children}</section>;
}

export type Tone = "draft" | "reviewed" | "bad" | "model" | "plain";
const TONE: Record<Tone, string> = {
  draft: "bg-mc-llm-bg text-mc-llm", reviewed: "bg-mc-human-bg text-mc-human", bad: "bg-mc-bad-bg text-mc-bad", model: "bg-mc-accent-bg text-mc-accent", plain: "bg-mc-surface-2 text-mc-muted",
};
const TONE_DOT: Record<Tone, string> = {
  draft: "bg-mc-dot-draft", reviewed: "bg-mc-dot-reviewed", bad: "bg-mc-dot-bad", model: "bg-mc-dot-model", plain: "bg-mc-dot-none",
};

export function Tag({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-px text-xs font-semibold ${TONE[tone]}`} title={title}>
      <span aria-hidden="true" className={`h-[7px] w-[7px] rounded-full ${TONE_DOT[tone]}`} />
      {children}
    </span>
  );
}

export function ReviewTag({ state }: { state: ReviewState | "none" }) {
  if (state === "reviewed") return <Tag title="A review was recorded for this content. Recorded review does not establish clinical validation." tone="reviewed">Reviewed</Tag>;
  if (state === "out of date") return <Tag title="The content changed after its recorded review" tone="bad">Review out of date</Tag>;
  if (state === "draft") return <Tag tone="draft">LLM draft</Tag>;
  return null;
}

// The case text changed after this output was made; it keeps its own status until regenerated.
export function OutdatedTag({ reason, output }: { reason: "task" | "solution"; output: "rubric" | "response" }) {
  const changed = reason === "task" ? "Task" : "Solution";
  return <Tag title={`The ${changed} was edited after this ${output} was made. ${output === "rubric" ? "Generate a new rubric" : "Collect a new response"} to use the current text.`} tone="bad">Out of date: {changed} updated</Tag>;
}

// One tag per reason a score is provisional (lens.ts provisionalReasons); never folded into review status.
const LIMIT: Array<[RegExp, string]> = [[/off-rubric/, "Off-rubric harm not scored"], [/unmatched/, "Unmatched statements read provisionally"], [/inputs not recorded/, "Unverified score"]];
export function LimitTags({ limits }: { limits: string[] }) {
  return <>{limits.map((reason) => <Tag key={reason} title={reason} tone="plain">{LIMIT.find(([re]) => re.test(reason))?.[1] ?? "Provisional"}</Tag>)}</>;
}

export function F1Tags({ summary }: { summary: F1Summary }) {
  return (
    <>
      {summary.draft && <Tag tone="draft">LLM draft</Tag>}
      {summary.provisional && <Tag tone="plain">Provisional</Tag>}
    </>
  );
}

const FILLED: Record<string, number> = { none: 0, uncertain: 0, mild: 1, moderate: 2, severe: 3 };
export function Severity({ level }: { level: string | null | undefined }) {
  if (!level) return <span className="text-xs text-mc-faint">Not rated</span>;
  const filled = FILLED[level] ?? 0;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-mc-line px-1.5 py-px text-xs" title={`Harm if not addressed: ${LEVEL[level] ?? level}`}>
      {LEVEL[level] ?? level}
      <span aria-hidden="true" className="inline-flex gap-0.5">
        {[1, 2, 3].map((i) => <i className={`h-1.5 w-1.5 rounded-full ${i <= filled ? "bg-mc-ink" : "bg-mc-line-strong"}`} key={i} />)}
      </span>
    </span>
  );
}

export function ScoreBadge({ value }: { value: number | null }) {
  const tone = value === null ? "bg-mc-surface-2 text-mc-muted" : value >= 7 ? "bg-mc-human-bg text-mc-human" : value >= 4 ? "bg-mc-llm-bg text-mc-llm" : "bg-mc-bad-bg text-mc-bad";
  return <span className={`min-w-[26px] shrink-0 rounded-md px-1.5 py-px text-center font-mc-mono text-xs ${tone}`}>{value ?? "-"}</span>;
}

export interface ChipOption { key: string; label: string; href: string; current: boolean }
export function Chips({ label, options }: { label: string; options: ChipOption[] }) {
  return (
    <nav aria-label={label} className="flex flex-wrap gap-1">
      {options.map((o) => (
        <Link
          aria-current={o.current ? "true" : undefined}
          className={`rounded-md border px-2.5 py-1 text-xs font-medium no-underline transition-colors ${o.current ? "border-mc-accent bg-mc-accent text-white" : "border-mc-line-strong bg-mc-surface text-mc-ink hover:border-mc-ink"}`}
          href={o.href}
          key={o.key}
        >
          {o.label}
        </Link>
      ))}
    </nav>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-mc-muted">{label}</div>
      {children}
    </div>
  );
}

export function Prose({ children, inline = false }: { children: ReactNode; inline?: boolean }) {
  if (typeof children === "string") return <PipelineMarkdown inline={inline}>{children}</PipelineMarkdown>;
  return inline ? <span>{children}</span> : <div className="leading-relaxed">{children}</div>;
}

export function fmt(x: number | null | undefined): string {
  return x === null || x === undefined ? "-" : x.toFixed(3);
}

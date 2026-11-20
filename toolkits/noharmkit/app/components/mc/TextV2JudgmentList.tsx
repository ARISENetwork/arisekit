"use client";

import { useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { EvidenceSelectionContext } from "@/components/mc/EvidenceLinker";
import { Prose, Tag } from "@/components/mc/ui";
import { applicabilityText } from "@/lib/text-v2-applicability";
import type { EvidenceTarget } from "@/lib/caseset/evidence-selection";
import styles from "./TextV2JudgmentList.module.css";

export interface JudgmentQuote { key: string; actionable: boolean; evidence: string; notFound: boolean }
export interface JudgmentItem extends JudgmentQuote { rowId: string; text: string; role: "first" | "addOn" | "alternative" | "fallback"; completeness: "complete" | "partial" | "absent"; missing: string }
export interface JudgmentCriterion {
  id: string;
  question: string;
  applicability: { state: "applicable" | "notApplicable" | "uncertain"; basis: string; evidence: string };
  items: JudgmentItem[];
  unmatched: JudgmentQuote[];
  contradiction: string[];
}
export interface JudgmentListData { criteria: JudgmentCriterion[]; offRubric: JudgmentQuote[] }

const ROLE: Record<JudgmentItem["role"], string> = { first: "First approach", addOn: "Add-on", alternative: "Alternative", fallback: "Later care or fallback" };
const COMPLETENESS: Record<JudgmentItem["completeness"], string> = { complete: "Complete", partial: "Partial", absent: "Absent" };

// Wraps a StepFrame so quotes are marked in Input only while selected, and Input stays in view beside the list.
export function JudgmentEvidenceFrame({ children }: { children: ReactNode }): ReactNode {
  return <div className={styles.frame}>{children}</div>;
}

// Brings the first selected quote into view inside the sticky Input column without scrolling the page.
export function EvidenceScroll(): ReactNode {
  const { active } = useContext(EvidenceSelectionContext);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!active) return;
    let box = ref.current?.parentElement ?? null;
    while (box && getComputedStyle(box).overflowY !== "auto") box = box.parentElement;
    const mark = box?.querySelector("mark[data-evidence-active]");
    if (!box || !mark) return;
    const view = box.getBoundingClientRect();
    const at = mark.getBoundingClientRect();
    if (at.top >= view.top + 48 && at.bottom <= view.bottom - 24) return;
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    box.scrollTo({ top: box.scrollTop + at.top - view.top - view.height / 3, behavior: smooth ? "smooth" : "auto" });
  }, [active]);
  return <span ref={ref} hidden />;
}

function foundKeys(quotes: JudgmentQuote[]): string[] {
  return quotes.filter(q => !q.notFound).map(q => q.key);
}

function criterionTarget(c: JudgmentCriterion): EvidenceTarget {
  return { id: c.id, keys: foundKeys([...c.items, ...c.unmatched]) };
}

function useSelected(ids: string[]): boolean {
  const { active } = useContext(EvidenceSelectionContext);
  return active !== null && ids.includes(active.id);
}

function Summary({ c }: { c: JudgmentCriterion }): ReactNode {
  const count = (state: JudgmentItem["completeness"]): number => c.items.filter(item => item.completeness === state).length;
  const notFound = [...c.items, ...c.unmatched].filter(q => q.notFound).length;
  return <span className={styles.summary}>
    {c.applicability.state === "notApplicable" && <Tag tone="plain">Does not apply</Tag>}
    {c.applicability.state === "uncertain" && <Tag tone="draft">Applicability unclear</Tag>}
    {count("complete") > 0 && <Tag tone="plain">{count("complete")} complete</Tag>}
    {count("partial") > 0 && <Tag tone="draft">{count("partial")} partial</Tag>}
    {count("absent") > 0 && <Tag tone="draft">{count("absent")} absent</Tag>}
    {c.items.length === 0 && c.applicability.state === "applicable" && <Tag tone="bad">No match</Tag>}
    {c.unmatched.length > 0 && <Tag tone="draft">{c.unmatched.length} not in rubric</Tag>}
    {c.contradiction.length > 0 && <Tag tone="bad">Contradiction</Tag>}
    {notFound > 0 && <Tag tone="bad">{notFound} quote not found</Tag>}
  </span>;
}

function Quote({ quote }: { quote: JudgmentQuote }): ReactNode {
  return <span className={styles.quote}><Prose>{quote.evidence}</Prose>{quote.notFound && <span className={styles.notFound}>Not found word for word in the response.</span>}</span>;
}

function Applicability({ c }: { c: JudgmentCriterion }): ReactNode {
  const a = c.applicability;
  return <div className={styles.applies}>
    <span>{applicabilityText(a)}{a.evidence ? ":" : ""}</span>
    {a.evidence && <span className={styles.quote}><Prose>{a.evidence}</Prose></span>}
  </div>;
}

function QuoteRow({ quote, parent, children }: { quote: JudgmentQuote; parent: EvidenceTarget; children: ReactNode }): ReactNode {
  const { dispatch } = useContext(EvidenceSelectionContext);
  const selected = useSelected([quote.key]);
  const target = { id: quote.key, keys: quote.notFound ? [] : [quote.key] };
  return <button type="button" className={styles.item} data-selected={selected ? "true" : undefined}
    onPointerEnter={() => dispatch({ type: "hover", target })} onPointerLeave={() => dispatch({ type: "hover", target: parent })}
    onFocus={() => dispatch({ type: "focus", target })} onBlur={() => dispatch({ type: "blur", id: quote.key })}
    onKeyDown={event => { if (event.key === "Escape") dispatch({ type: "dismiss" }); }}>
    {children}
  </button>;
}

function Details({ c }: { c: JudgmentCriterion }): ReactNode {
  const parent = criterionTarget(c);
  return <div className={styles.details}>
    <Applicability c={c} />
    {c.items.length > 0 && <div className={styles.group}>
      <span className={styles.groupTitle}>Matched rubric items</span>
      {c.items.map(item => <QuoteRow key={item.key} quote={item} parent={parent}>
        <span className={styles.itemHead}>
          <span className={styles.itemText}><Prose inline>{item.text}</Prose></span>
          <span className={styles.itemMeta}>
            <span>{ROLE[item.role]}</span>
            <span data-tone={item.completeness === "complete" ? undefined : "draft"}>{COMPLETENESS[item.completeness]}</span>
            {!item.actionable && <span>Not actionable</span>}
          </span>
        </span>
        <Quote quote={item} />
        {item.missing && <span className={styles.missing}>Missing: {item.missing}</span>}
      </QuoteRow>)}
    </div>}
    {c.items.length === 0 && c.applicability.state === "applicable" && <p className={styles.empty}>No rubric items matched.</p>}
    {c.unmatched.length > 0 && <div className={styles.group}>
      <span className={styles.groupTitle}>Statements not in the rubric</span>
      {c.unmatched.map(quote => <QuoteRow key={quote.key} quote={quote} parent={parent}>
        <span className={styles.itemMeta}><span data-tone="draft">{quote.actionable ? "Actionable" : "Not actionable"}</span></span>
        <Quote quote={quote} />
      </QuoteRow>)}
    </div>}
    {c.contradiction.length > 0 && <div className={styles.group}>
      <span className={styles.groupTitle} data-tone="bad">Contradiction</span>
      {c.contradiction.map((text, index) => <span key={index} className={styles.quote}><Prose>{text}</Prose></span>)}
    </div>}
  </div>;
}

function CriterionRow({ c }: { c: JudgmentCriterion }): ReactNode {
  const [open, setOpen] = useState(false);
  const { dispatch } = useContext(EvidenceSelectionContext);
  const target = criterionTarget(c);
  const active = useSelected([c.id, ...target.keys]);
  return <section className={styles.row} data-active={active ? "true" : undefined}
    onPointerEnter={() => dispatch({ type: "hover", target })} onPointerLeave={() => dispatch({ type: "leave", id: c.id })}>
    <button type="button" className={styles.rowHead} aria-expanded={open} onClick={() => setOpen(value => !value)}
      onFocus={() => dispatch({ type: "focus", target })} onBlur={() => dispatch({ type: "blur", id: c.id })}>
      <svg aria-hidden="true" className={styles.chevron} data-open={open ? "true" : undefined} width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M4.5 2.5 8 6l-3.5 3.5" /></svg>
      <span className={styles.question}><span className={styles.cid}>{c.id}</span>{c.question}</span>
      <Summary c={c} />
    </button>
    <div className={styles.collapse} data-open={open ? "true" : undefined} inert={!open ? true : undefined}>
      <div className={styles.collapseInner}><Details c={c} /></div>
    </div>
  </section>;
}

function OffRubric({ data }: { data: JudgmentListData }): ReactNode {
  if (!data.offRubric.length) return null;
  const parent = { id: "off", keys: foundKeys(data.offRubric) };
  return <section className={styles.card}>
    <header className={styles.cardHead}><span className={styles.question}>Statements outside every criterion</span></header>
    <div className={styles.cardBody}><div className={styles.group}>
      {data.offRubric.map(quote => <QuoteRow key={quote.key} quote={quote} parent={parent}>
        <span className={styles.itemMeta}><span>{quote.actionable ? "Actionable" : "Not actionable"}</span></span>
        <Quote quote={quote} />
      </QuoteRow>)}
      <p className={styles.empty}>These statements are kept without a rubric error severity.</p>
    </div></div>
  </section>;
}

const list = (ids: string[]): string => ids.length < 3 ? ids.join(" and ") : `${ids.slice(0, -1).join(", ")} and ${ids.at(-1)}`;
const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

// One line on what the judgment found, so problems show without opening every criterion.
export function judgmentVerdict(data: JudgmentListData): { headline: string; details: string[] } {
  const applicable = data.criteria.filter(c => c.applicability.state !== "notApplicable");
  const missed = applicable.filter(c => c.applicability.state === "applicable" && c.items.length === 0).map(c => c.id);
  // A criterion that may not apply and has no match is neither matched nor missed.
  const unsure = applicable.filter(c => c.applicability.state === "uncertain" && c.items.length === 0).map(c => c.id);
  const matched = applicable.filter(c => c.items.length > 0).length;
  const partial = data.criteria.flatMap(c => c.items).filter(item => item.completeness !== "complete").length;
  const outside = data.criteria.reduce((n, c) => n + c.unmatched.length, 0) + data.offRubric.length;
  const skipped = data.criteria.length - applicable.length;
  const headline = missed.length
    ? `${matched} of ${applicable.length} criteria matched; ${list(missed)} had no match.`
    : matched < applicable.length ? `${matched} of ${applicable.length} criteria matched.`
    : applicable.length === 1 ? "The one applicable criterion matched." : `All ${applicable.length} applicable criteria matched.`;
  const details = [
    unsure.length ? `${list(unsure)} may not apply and had no match.` : "",
    partial ? `${plural(partial, "matched item is", "matched items are")} partial.` : "",
    outside ? `${plural(outside, "statement is", "statements are")} not in the rubric.` : "",
    skipped ? `${plural(skipped, "criterion does", "criteria do")} not apply.` : "",
  ].filter(Boolean);
  return { headline, details };
}

export default function TextV2JudgmentList({ data }: { data: JudgmentListData }): ReactNode {
  const verdict = judgmentVerdict(data);
  return <div className={styles.stack}>
    <p className={styles.verdict} role="status"><strong>{verdict.headline}</strong>{verdict.details.length > 0 && <> <span>{verdict.details.join(" ")}</span></>}</p>
    <div className={styles.list}>{data.criteria.map(c => <CriterionRow key={c.id} c={c} />)}</div>
    <OffRubric data={data} />
  </div>;
}

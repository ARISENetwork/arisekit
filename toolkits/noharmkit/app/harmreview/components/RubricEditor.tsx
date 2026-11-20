"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { DragEvent as ReactDragEvent, ReactNode } from "react";

import RemovalDialog, { type RemovalRequest } from "./RemovalDialog";
import RubricPanel from "@/harmreview/components/RubricPanel";
import editorStyles from "./RubricEditor.module.css";
import panelStyles from "./RubricPanel.module.css";
import CaseSourcePanel from "@/harmreview/components/CaseSourcePanel";
import Dropdown from "@/harmreview/components/Dropdown";
import { newTiming, recordEdit, recordInteraction, USUAL_CARE_QUESTION } from "@/harmreview/lib/rubric";
import type { AuthoringTiming, NeedSeverity, Score } from "@/harmreview/lib/rubric";
import { useReviewerId } from "@/harmreview/lib/reviewer-id";
import type { CaseSource } from "@/harmreview/lib/types";
import { addV2Criterion, criterionOmissionHarm, isOmissionItem, newV2Item, omissionItem, ratingTooltip, setV2Score, unratedV2Count, V2_OMISSION_TEXT, V2_SCORE_HELP, V2_SEVERITY_HELP, v2Issues, validateTextV2 } from "@/harmreview/lib/rubric-text-v2";
import type { TextV2Case, TextV2Criterion, TextV2Item, TextV2Provenance } from "@/harmreview/lib/rubric-text-v2";
import { useRubricEditorHost, type TextV2EditorHost } from "@/components/RubricEditorHost";

// What the guided tutorial (D190) reads and changes in the editor it runs on.
export interface TutorialControls {
  record: TextV2Case;
  openIds: ReadonlySet<string>;
  setOpenIds: (ids: string[]) => void;
  updateRecord: (change: (record: TextV2Case) => TextV2Case) => void;
}
export interface EditorTutorial { record: TextV2Case; source: CaseSource; overlay: (controls: TutorialControls) => ReactNode }

type SaveStatus = "clean" | "dirty" | "saved" | "error";

const SEVERITIES: NeedSeverity[] = ["none", "mild", "moderate", "severe"];
const SEVERITY_LABEL: Record<NeedSeverity, string> = { none: "None", mild: "Mild", moderate: "Moderate", severe: "Severe" };
const SCORES: Score[] = [1, 2, 3, 4, 5, 6, 7, 8, 9];

const ROW_GRID = "grid";
const muted = "text-[hsl(var(--muted-foreground))]";
const smallSelect = "h-7 rounded-md border px-1.5 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]/40";
// Neutral chip for adding rows and Decisions (design canvas Round 3, option C).
const chipButton = "rounded border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2 py-0.5 text-[11px] font-semibold text-[hsl(var(--foreground))] transition-colors hover:border-[hsl(var(--primary))]/50 hover:bg-[hsl(var(--primary))]/5";
// Every header button (Guide, Tutorial, Reset) shares this shape; the Guide is filled so reviewers notice it.
const headerButtonShape = "inline-flex min-h-9 items-center rounded-md border px-2.5 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[hsl(var(--primary))] motion-reduce:transition-none";
const headerButton = `${headerButtonShape} border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))]`;
const guideButton = `${headerButtonShape} border-transparent bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] hover:brightness-95`;
// Edits save themselves this long after the last change.
const AUTOSAVE_MS = 800;
const iconButton = "inline-flex h-6 w-6 items-center justify-center rounded text-[hsl(var(--muted-foreground))]/70 transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]";

function shortId(id: string): string {
  return id.replace(/^[DC]/, "").replace(".O", ".");
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg aria-hidden="true" className={`h-3.5 w-3.5 transition-transform duration-200 motion-reduce:transition-none ${open ? "rotate-90" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path d="m9 6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} />
    </svg>
  );
}

function IconX() {
  return (
    <svg aria-hidden="true" className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path d="M6 18 18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} />
    </svg>
  );
}

// Single-line clinical text that wraps and grows instead of scrolling sideways.
function AutoText({ value, onChange, className = "", ...props }: Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "onChange" | "value"> & { value: string; onChange: (value: string) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const fit = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, []);
  useLayoutEffect(fit, [value, fit]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let width = el.offsetWidth;
    const observer = new ResizeObserver(() => { if (el.offsetWidth !== width) { width = el.offsetWidth; fit(); } });
    observer.observe(el);
    return () => observer.disconnect();
  }, [fit]);
  return (
    <textarea
      {...props}
      className={`-mx-1.5 block w-[calc(100%+0.75rem)] resize-none! overflow-hidden rounded bg-transparent px-1.5 py-0.5 leading-5 text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]/70 transition-colors hover:bg-[hsl(var(--muted))]/60 focus:bg-[hsl(var(--card))] ${className}`}
      ref={ref}
      rows={1}
      value={value}
      onChange={(event) => onChange(event.target.value.replace(/\n/g, " "))}
      onKeyDown={(event) => {
        if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
        event.preventDefault();
        event.currentTarget.blur();
      }}
    />
  );
}

// Red (1) to blue (9) through neutral. Static class strings so Tailwind keeps them.
const SCORE_FILL: Record<Score, string> = {
  1: "bg-[#b91c1c] text-white", 2: "bg-[#dc2626] text-white", 3: "bg-[#f87171] text-red-950",
  4: "bg-[#fecaca] text-red-950", 5: "bg-[#d6d3d1] text-stone-900", 6: "bg-[#bfdbfe] text-blue-950",
  7: "bg-[#60a5fa] text-blue-950", 8: "bg-[#2563eb] text-white", 9: "bg-[#1e40af] text-white",
};
// Dark mode tints the same hues over the card, strongest at the ends of the scale.
const SCORE_TINT: Record<Score, string> = {
  1: "bg-[#f1d2d2] text-red-900/70 dark:bg-red-500/30", 2: "bg-[#f8d4d4] text-red-900/70 dark:bg-red-500/24", 3: "bg-[#fee3e3] text-red-900/70 dark:bg-red-500/18",
  4: "bg-[#fff1f1] text-red-900/60 dark:bg-red-500/12", 5: "bg-[#f5f4f3] text-stone-600 dark:bg-stone-400/14", 6: "bg-[#eff6ff] text-blue-900/60 dark:bg-blue-500/12",
  7: "bg-[#dfedfe] text-blue-900/70 dark:bg-blue-500/18", 8: "bg-[#d3e0fb] text-blue-900/70 dark:bg-blue-500/24", 9: "bg-[#d2d9ef] text-blue-900/70 dark:bg-blue-500/30",
};

// Horizontal 1-9 appropriateness bar with a tooltip per number.
function ScoreBar({ label, value, onChange, descriptions }: { label: string; value: Score | null; onChange: (score: Score) => void; descriptions: Readonly<Record<Score, string>> }) {
  // The tooltip keeps its last position while fading out.
  const [tip, setTip] = useState<{ score: Score; x: number; y: number; visible: boolean } | null>(null);
  const show = (score: Score, el: HTMLElement): void => {
    const r = el.getBoundingClientRect();
    setTip({ score, x: r.left + r.width / 2, y: r.top, visible: true });
  };
  const hide = (): void => setTip((t) => t && { ...t, visible: false });
  const describe = (s: Score): string => descriptions[s];
  return (
    <div aria-label={label} className="flex gap-0.5 pl-3" data-rating-bar role="group" onMouseLeave={hide}>
      {SCORES.map((s) => {
        const on = value === s;
        return (
          <button
            aria-label={`${s}: ${describe(s)}`}
            aria-pressed={on}
            className={`h-5 w-[18px] rounded-[3px] text-[11px] leading-5 transition-[filter,box-shadow] hover:brightness-95 ${on ? `font-bold ring-2 ring-inset ring-black/35 ${SCORE_FILL[s]}` : SCORE_TINT[s]}`}
            key={s}
            type="button"
            onBlur={hide}
            onClick={() => { hide(); onChange(s); }}
            onFocus={(event) => show(s, event.currentTarget)}
            onMouseEnter={(event) => show(s, event.currentTarget)}
          >
            {s}
          </button>
        );
      })}
      <div
        aria-hidden="true"
        className={`pointer-events-none fixed z-50 w-64 -translate-x-1/2 -translate-y-full rounded-md bg-[hsl(var(--tip))] px-2.5 py-1.5 text-[11.5px] leading-snug text-[hsl(var(--tip-foreground))] shadow-lg transition-opacity duration-150 motion-reduce:transition-none ${tip?.visible ? "opacity-100" : "opacity-0"}`}
        style={tip ? { left: tip.x, top: tip.y - 6 } : { left: -9999, top: -9999 }}
      >
        {tip && describe(tip.score).split("\n").map((line, index) => <p className={index ? "mt-1 text-[hsl(var(--tip-foreground))]/75" : ""} key={line}>{line}</p>)}
      </div>
    </div>
  );
}

// Amber notice panel: draft warnings and an out-of-date saved copy.
const warnPanel = "border border-amber-200 bg-amber-50 px-3.5 py-2 text-[12.5px] text-amber-900 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-200";
const lockedPill = "inline-block whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-semibold leading-5";

// A harm cell's explanation, shown above it on hover or focus; it fades both ways
// and keeps its last position while fading out, like the score bar's tooltip.
function HoverTip({ text, children }: { text: string; children: (describedBy: string) => React.ReactNode }) {
  const id = useId();
  const [tip, setTip] = useState<{ x: number; y: number; visible: boolean } | null>(null);
  const show = (el: HTMLElement): void => {
    const r = el.getBoundingClientRect();
    setTip({ x: r.left + r.width / 2, y: r.top, visible: true });
  };
  const hide = (): void => setTip((t) => t && { ...t, visible: false });
  return (
    <div className="pl-3" onBlur={hide} onFocus={(event) => show(event.currentTarget)} onMouseEnter={(event) => show(event.currentTarget)} onMouseLeave={hide}>
      {children(id)}
      <div
        className={`pointer-events-none fixed z-50 w-64 -translate-x-1/2 -translate-y-full rounded-md bg-[hsl(var(--tip))] px-2.5 py-1.5 text-[11.5px] leading-snug text-[hsl(var(--tip-foreground))] shadow-lg transition-opacity duration-150 motion-reduce:transition-none ${tip?.visible ? "opacity-100" : "opacity-0"}`}
        id={id}
        role="tooltip"
        style={tip ? { left: tip.x, top: tip.y - 6 } : { left: -9999, top: -9999 }}
      >
        {text}
      </div>
    </div>
  );
}

// A row's number cell: a fixed grip slot and a slot for the add-on button (both empty on rows that cannot move), then
// the number, so grips, buttons and numbers each line up in their own column.
function NumberCell({ label, grip = false, gripClass = "", action }: { label: string; grip?: boolean; gripClass?: string; action?: ReactNode }) {
  return (
    <span className={`flex items-center gap-1 pl-1 pt-0.5 text-[11px] leading-5 ${muted}`}>
      <span aria-hidden="true" className={`w-3 shrink-0 select-none text-center text-[12px] font-bold text-[hsl(var(--foreground))] ${gripClass}`}>{grip ? "⋮⋮" : ""}</span>
      <span className="-my-0.5 flex w-6 shrink-0">{action}</span>
      <span>{label}</span>
    </span>
  );
}

const V2_SCORE_DESCRIPTORS = Object.fromEntries(Object.entries(V2_SCORE_HELP).map(([score, help]) => [score, ratingTooltip(help)])) as Record<Score, string>;

// An icon button's label, shown at once on hover or focus (a native title waits about a second).
function QuickTip({ text, children }: { text: string; children: React.ReactNode }) {
  const [tip, setTip] = useState<{ x: number; y: number; visible: boolean } | null>(null);
  const show = (el: HTMLElement): void => {
    const r = el.getBoundingClientRect();
    setTip({ x: r.left + r.width / 2, y: r.top, visible: true });
  };
  const hide = (): void => setTip((t) => t && { ...t, visible: false });
  return (
    <span className="inline-flex" onBlur={hide} onFocus={(event) => show(event.currentTarget)} onMouseEnter={(event) => show(event.currentTarget)} onMouseLeave={hide}>
      {children}
      <span
        aria-hidden="true"
        className={`pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md bg-[hsl(var(--tip))] px-2 py-1 text-[11.5px] leading-snug text-[hsl(var(--tip-foreground))] shadow-lg transition-opacity duration-100 motion-reduce:transition-none ${tip?.visible ? "opacity-100" : "opacity-0"}`}
        style={tip ? { left: tip.x, top: tip.y - 6 } : { left: -9999, top: -9999 }}
      >
        {text}
      </span>
    </span>
  );
}

function harmTone(harm: NeedSeverity): string {
  return harm === "none" ? "bg-mc-surface-2 text-mc-ink" : harm === "mild" ? "bg-amber-50 text-amber-900 dark:bg-amber-400/15 dark:text-amber-200" : "bg-orange-50 text-orange-900 dark:bg-orange-400/15 dark:text-orange-200";
}

// Every card (D0 usual care, D1 Follow-up, and the rest) shares this shell:
// collapse arrow, ID, question, header controls when open, summary when closed.
function Card({
  id,
  label,
  question,
  editableQuestion,
  issues,
  open,
  onToggle,
  openControls,
  closedPill,
  children,
}: {
  id: string;
  label?: string;
  question: string;
  editableQuestion?: React.ReactNode;
  issues: string[];
  open: boolean;
  onToggle: () => void;
  openControls?: React.ReactNode;
  closedPill: React.ReactNode;
  children: React.ReactNode;
}) {
  const bodyId = `${id}-body`;
  return (
    <section aria-label={id} data-rubric-card className="scroll-mt-24 overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" id={id}>
      <div className={`flex items-center gap-2.5 px-3 py-2 transition-colors ${open ? "border-b border-[hsl(var(--border))] bg-[hsl(var(--primary))]/[0.06]" : "bg-[hsl(var(--card))]"}`}>
        <button aria-controls={bodyId} aria-expanded={open} aria-label={`${open ? "Collapse" : "Expand"} ${id}`} className={`${iconButton} shrink-0`} type="button" onClick={onToggle}>
          <Chevron open={open} />
        </button>
        <span className={`w-6 shrink-0 text-xs font-bold ${muted}`}>{label ?? id}</span>
        {open && editableQuestion
          ? <div className="min-w-0 flex-1">{editableQuestion}</div>
          : (
            <button className="min-w-0 flex-1 py-0.5 text-left text-[14px] font-semibold leading-snug" type="button" onClick={onToggle}>
              {question || <span className={muted}>Untitled Criterion</span>}
            </button>
          )}
        {open
          ? <div className="flex shrink-0 items-center gap-2">{openControls}</div>
          : (
            <div className="flex shrink-0 items-center gap-3">
              {issues.length > 0 && <span className="text-xs font-bold text-orange-700 dark:text-orange-300">{issues.length} issue{issues.length === 1 ? "" : "s"}</span>}
              {closedPill}
            </div>
          )}
      </div>
      <div className={`group-content-wrapper ${open ? "expanded" : ""}`} data-decision-body id={bodyId} inert={!open ? true : undefined}>
        <div className="group-content-inner">{children}</div>
      </div>
    </section>
  );
}

const pillClass = "rounded-full bg-blue-50 px-2 py-0.5 text-[11.5px] font-bold text-blue-800 dark:bg-blue-400/15 dark:text-blue-200";
const flagClass = "rounded-full bg-amber-50 px-2 py-0.5 text-[11.5px] font-bold text-amber-900 dark:bg-amber-400/15 dark:text-amber-200";

// C1: usual care is row 1.1 in the criteria grid, with a score (D138). Its harm caps every .0 row (D130).
type UsualCareValue = NonNullable<TextV2Case["usualCare"]>;

function UsualCareCard({ value, issues, open, onToggle, onChange }: { value: UsualCareValue; issues: string[]; open: boolean; onToggle: () => void; onChange: (value: UsualCareValue) => void }) {
  const usualScore = value.score ?? null;
  return (
    <Card
      closedPill={<span className={value.harm ? pillClass : `rounded-full bg-[hsl(var(--muted))] px-2 py-0.5 text-[11.5px] font-bold ${muted}`}>{value.harm ? SEVERITY_LABEL[value.harm] : "Not rated"}</span>}
      id="D0" label="C1" issues={issues} open={open} question={USUAL_CARE_QUESTION} onToggle={onToggle}
    >
      <div data-usual-care-row>
        <div data-row-grid data-row-header className={`${ROW_GRID} items-end pb-0.5 pt-2.5 text-[11px] ${muted}`}>
          <span />
          <span />
          <span className="pl-3">Clinical Appropriateness</span>
          <span className="pl-3">Error Severity</span>
          <span />
        </div>
        <div data-row-grid className={`${ROW_GRID} items-start py-1.5 text-[13.5px]`}>
          <NumberCell label="1.1" />
          <p className="min-w-0 pt-0.5">Continue current management or usual care, without additional input</p>
          <div className={`rounded-md ${usualScore === null ? UNRATED_RING : ""}`} data-unrated={usualScore === null || undefined}>
            <ScoreBar descriptions={V2_SCORE_DESCRIPTORS} label="Score for usual care" value={usualScore} onChange={(score) => onChange({ ...value, score })} />
          </div>
          <HoverTip text="The error severity if the patient only continues current management. It caps the error severity of every unaddressed criterion.">{(describedBy) => <div aria-describedby={describedBy}>
            <V2HarmSelect label="Harm of usual care without additional input" value={value.harm} onChange={(harm) => onChange({ ...value, harm })} />
          </div>}</HoverTip>
          <span />
        </div>
      </div>
    </Card>
  );
}

// Rubric format text v2 (D123-D130): every item has a harm if followed; followup and plan criteria carry a
// reviewed harm if missed; the counseling criterion's is computed from its required items and shown locked.
export interface LoadedV2 {
  record: TextV2Case;
  provenance: TextV2Provenance;
  source: CaseSource;
  timing?: AuthoringTiming;
  savedAt?: string;
  fromCopy: boolean;
  // A saved copy that started from a different version of the rubric than the one now loaded.
  sourceChanged?: boolean;
}

function UnresolvedNote({ note }: { note: string }) {
  return <p className="mt-1 text-xs leading-5 text-amber-900 dark:text-amber-200" data-unresolved><span className={flagClass}>Unresolved</span> {note}</p>;
}

function V2HarmSelect({ label, value, onChange }: { label: string; value: NeedSeverity | null | undefined; onChange: (value: NeedSeverity | null) => void }) {
  return (
    <Dropdown
      aria-label={label}
      className={`${smallSelect} w-full ${value == null ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-400/50 dark:bg-amber-400/10 dark:text-amber-200" : `border-[hsl(var(--border))] ${harmTone(value)}`}`}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value ? event.target.value as NeedSeverity : null)}
    >
      {value == null && <option value="">Rate severity</option>}
      {SEVERITIES.map((severity) => <option data-description={ratingTooltip(V2_SEVERITY_HELP[severity])} key={severity} value={severity}>{SEVERITY_LABEL[severity]}</option>)}
    </Dropdown>
  );
}

// An unrated score must be rated: the same amber as an unrated harm dropdown, outlined on all four sides.
const UNRATED_RING = "ring-1 ring-amber-400 bg-amber-50 dark:bg-amber-400/10";

// D142: harm columns rate error severity, measured against the best option for this patient.
const V2_APPROACH_ERROR_HELP = "None for the best option, even if it carries inherent risk; an acceptable but inferior option can be Mild. Includes anything this approach leaves undone, such as a delay or a missed diagnosis.";
const V2_ADDON_ERROR_HELP = "The error of adding this. None if it is harmless. Add-ons never count toward the criterion.";
const V2_OMISSION_ERROR_HELP = "The error of leaving this criterion unaddressed. It may not exceed the error severity of usual care.";

const V2_FOLLOWED_HELP = "Harm if a patient follows this plan, including what it leaves untreated.";
const V2_MISSED_HELP = "Harm if this need is missed. It may not exceed the harm of usual care.";

function IconMove() {
  return (
    <svg aria-hidden="true" className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path d="M7 4v16M7 20l-3-3M7 20l3-3M17 20V4M17 4l-3 3M17 4l3 3" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} />
    </svg>
  );
}

// The browser draws its own drag picture from the row's box including its hidden tooltips and closed menus, which
// reach far past the row, so the picture carried nearby content too. It is drawn from a plain copy of the row instead.
function setRowDragImage(event: ReactDragEvent<HTMLDivElement>): void {
  const row = event.currentTarget;
  const box = row.getBoundingClientRect();
  const copy = row.cloneNode(true) as HTMLElement;
  copy.querySelectorAll('.fixed, [role="tooltip"], [role="listbox"]').forEach((element) => element.remove());
  const texts = row.querySelectorAll("textarea");
  copy.querySelectorAll("textarea").forEach((textarea, index) => { textarea.value = texts[index].value; });
  for (const name of ["data-v2-item", "data-v2-row", "draggable"]) copy.removeAttribute(name);
  const ghost = document.createElement("div");
  ghost.setAttribute("aria-hidden", "true");
  ghost.className = `${editorStyles.root} ${editorStyles.dragGhost}`;
  Object.assign(ghost.style, { left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px` });
  ghost.append(copy);
  document.body.append(ghost);
  event.dataTransfer.setDragImage(ghost, event.clientX - box.left, event.clientY - box.top);
  setTimeout(() => ghost.remove(), 0);
}

function TextV2ItemRow({ item, criterion, autoFocus, onTextFocus, onPatch, onScore, onRemove, side, onSide }: {
  item: TextV2Item; criterion: TextV2Criterion; autoFocus: boolean; onTextFocus: () => void;
  onPatch: (patch: Partial<TextV2Item>) => void; onScore: (score: Score) => void; onRemove: () => void;
  side: boolean; onSide: (side: boolean) => void;
}): ReactNode {
  const counseling = criterion.kind === "counseling";
  const harmLabel = counseling && !side ? "Harm if followed" : "Error Severity";
  const harmHelp = side ? V2_ADDON_ERROR_HELP : counseling ? V2_FOLLOWED_HELP : V2_APPROACH_ERROR_HELP;
  const followed = <HoverTip text={harmHelp}>{(describedBy) => <div aria-describedby={describedBy} data-severity-cell>
    <span className={`mb-1 text-xs ${muted}`} data-v2-cell-label>{harmLabel}</span>
    <V2HarmSelect label={`${harmLabel} for ${item.id}`} value={item.harm} onChange={(harm) => onPatch({ harm })} />
  </div>}</HoverTip>;
  const missed = "omissionHarm" in item
    ? <HoverTip text={V2_MISSED_HELP}>{(describedBy) => <div aria-describedby={describedBy}>
      <span className={`mb-1 text-xs ${muted}`} data-v2-cell-label>Harm if missed</span>
      <V2HarmSelect label={`Harm if ${item.id} is missed`} value={item.omissionHarm} onChange={(omissionHarm) => onPatch({ omissionHarm })} />
    </div>}</HoverTip>
    : <p className={`pl-3 pt-1 text-xs ${muted}`} data-v2-not-required>{item.optional ? "Optional: not required" : item.score === null ? "Score first" : "Not required"}</p>;
  return <div data-row-grid data-v2-row data-v2-item={item.id} className={`${ROW_GRID} group/role cursor-grab items-start py-1.5 text-[13.5px] active:cursor-grabbing`}
    draggable onDragStart={(event) => { event.dataTransfer.setData("text/v2-item", item.id); event.dataTransfer.effectAllowed = "move"; setRowDragImage(event); }}>
    <NumberCell grip gripClass="opacity-40 transition-opacity group-hover/role:opacity-100 group-focus-within/role:opacity-100" label={shortId(item.id)}
      action={<QuickTip text={side ? "Move to main approach" : "Move to add-on"}><button aria-label={side ? `Move ${item.id} to main approach` : `Move ${item.id} to add-on`} className={iconButton} data-move-role type="button" onClick={() => onSide(!side)}><IconMove /></button></QuickTip>} />
    <div className="min-w-0">
      <AutoText autoFocus={autoFocus} onFocus={onTextFocus} aria-label={`Item ${item.id}`} placeholder="Write the complete plan, including any condition and timing" value={item.text} onChange={(text) => onPatch({ text })} />
      {item.unresolved && <UnresolvedNote note={item.unresolved} />}
    </div>
    <div data-score-cell>
      <div className={`rounded-md ${item.score === null ? UNRATED_RING : ""}`} data-unrated={item.score === null || undefined}><ScoreBar descriptions={V2_SCORE_DESCRIPTORS} label={`Score for ${item.id}`} value={item.score} onChange={onScore} /></div>
    </div>
    {counseling && !side ? <div className="grid grid-cols-2 gap-1" data-v2-harm-pair>{followed}{missed}</div> : followed}
    <div className="flex justify-end gap-0.5 pr-2"><QuickTip text="Remove"><button aria-label={`Remove ${item.id}`} data-row-action className={`${iconButton} hover:!bg-red-50 hover:!text-red-600 dark:hover:!bg-red-400/15 dark:hover:!text-red-300`} type="button" onClick={onRemove}><IconX /></button></QuickTip></div>
  </div>;
}

// D146: Main approach (complete courses, generally one per response) above Add-ons (pieces and extras). An item moves
// between them by drag or by its move button.
function RoleSections({ criterion, rowFor, onRole, isSide, omission, unaddressed }: {
  criterion: TextV2Criterion; rowFor: (item: TextV2Item) => ReactNode; onRole: (id: string, side: boolean) => void;
  isSide: (item: TextV2Item) => boolean; omission?: ReactNode; unaddressed?: ReactNode;
}): ReactNode {
  const counseling = criterion.kind === "counseling";
  const [over, setOver] = useState<"main" | "side" | null>(null);
  // D154: rows glide to their new place when a score change or a move re-sorts them (FLIP: measure the old and new
  // position, then animate the difference away). Positions are relative to this card, so scrolling never animates.
  const container = useRef<HTMLDivElement>(null);
  const positions = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    const base = root.getBoundingClientRect().top;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const seen = new Map<string, number>();
    root.querySelectorAll<HTMLElement>("[data-v2-item]").forEach((row) => {
      const id = row.dataset.v2Item;
      if (!id) return;
      const top = row.getBoundingClientRect().top - base;
      const before = positions.current.get(id);
      if (!reduced && before !== undefined && Math.abs(before - top) > 1) {
        row.animate([{ transform: `translateY(${before - top}px)` }, { transform: "translateY(0)" }], { duration: 350, easing: "cubic-bezier(0.2, 0, 0, 1)" });
      }
      seen.set(id, top);
    });
    positions.current = seen;
  });
  const mainName = counseling ? "Main actions" : "Main approach";
  const sideName = "Add-ons";
  const zone = (side: boolean): ReactNode => {
    const key = side ? "side" : "main";
    // D154: each section re-sorts live by appropriateness, highest first; unscored items stay at the bottom in the
    // order they were added (Array.prototype.sort is stable).
    const items = criterion.recommendations.filter((item) => isSide(item) === side).sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    return <section
      aria-label={side ? sideName : mainName}
      className={`transition-colors ${side ? "border-t border-[hsl(var(--border))] bg-[hsl(var(--muted))]/35" : ""} ${over === key ? "bg-[hsl(var(--primary))]/5 ring-1 ring-inset ring-[hsl(var(--primary))]/40" : ""}`}
      data-role-zone={key}
      onDragLeave={() => setOver(null)}
      onDragOver={(event) => { if (event.dataTransfer.types.includes("text/v2-item")) { event.preventDefault(); setOver(key); } }}
      onDrop={(event) => { event.preventDefault(); setOver(null); const id = event.dataTransfer.getData("text/v2-item"); if (id) onRole(id, side); }}
    >
      <div data-row-grid data-row-header className={`${ROW_GRID} items-end pb-0.5 pt-2.5 text-[11px] ${muted}`}>
        <span />
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[12.5px] font-bold text-[hsl(var(--foreground))]">{side ? sideName : mainName}</span>
          <span>{side ? "good or bad extras alongside the main approach. They don't fulfill the criterion on their own" : counseling ? "all that apply are required" : "possible good or bad ways to address this criterion. Typically, a response only includes one"}</span>
          {!side && omission}
        </span>
        <span className="pl-3" data-score-cell>Clinical Appropriateness</span>
        {counseling && !side
          ? <span className="grid grid-cols-2 gap-1 pl-3"><span>Harm if followed</span><span className="pl-3">Harm if missed</span></span>
          : <span className="pl-3" data-severity-cell>Error Severity</span>}
        <span />
      </div>
      <div className="divide-y divide-[hsl(var(--border))]/60">{items.map(rowFor)}{!side && unaddressed}</div>
      {items.length === 0 && <div aria-label={`${side ? sideName : mainName}: none`} className={`${ROW_GRID} items-start py-1.5 text-[13.5px]`} data-empty-zone data-row-grid>
        <span />
        <p className={`min-w-0 pt-0.5 italic ${muted}`}>{side ? "None. Drag an item here to change it to an add-on" : "None"}</p>
      </div>}
    </section>;
  };
  return <div className="divide-y divide-[hsl(var(--border))]" ref={container}>{zone(false)}{zone(true)}</div>;
}

function TextV2CriterionCard({ criterion, record, issues, open, onToggle, onChange, onRemove, onRequestRemoval }: {
  criterion: TextV2Criterion; record: TextV2Case; issues: string[]; open: boolean; onToggle: () => void;
  onChange: (updater: (criterion: TextV2Criterion) => TextV2Criterion) => void; onRemove?: () => void;
  onRequestRemoval: (request: RemovalRequest) => void;
}): ReactNode {
  const [focusItemId, setFocusItemId] = useState<string | null>(null);
  // D162: the section is the record's addOn field; a legacy optional item counts as an add-on.
  const isSide = (item: TextV2Item): boolean => item.addOn === true || item.optional === true;
  const setRole = (id: string, side: boolean): void => onChange((current) => ({ ...current, recommendations: current.recommendations.map((item) => {
    if (item.id !== id) return item;
    const { addOn: _addOn, optional: _optional, ...rest } = item;
    return side ? { ...rest, addOn: true } : rest;
  }) }));
  // D139: the omission is item .0, shown as the last main approach (or the locked "worst if missed" pill for
  // counseling), never as an ordinary row.
  const omission = omissionItem(criterion);
  const visible = { ...criterion, recommendations: criterion.recommendations.filter((item) => !isOmissionItem(criterion, item)) };
  const setOmission = (change: Partial<TextV2Item>): void => onChange((current) => ({ ...current,
    recommendations: current.recommendations.map((item) => (isOmissionItem(current, item) ? { ...item, ...change } : item)) }));
  const patch = (id: string, change: Partial<TextV2Item>): void => onChange((current) => ({ ...current, recommendations: current.recommendations.map((item) => (item.id === id ? { ...item, ...change } : item)) }));
  const row = (item: TextV2Item): ReactNode => (
    <TextV2ItemRow
      autoFocus={focusItemId === item.id}
      criterion={criterion}
      item={item}
      key={item.id}
      onPatch={(change) => patch(item.id, change)}
      onRemove={() => onRequestRemoval({ title: "Remove item?", text: item.text || item.id, focusAfterRemove: `[data-add-v2-item="${criterion.id}"]`, onConfirm: () => onChange((current) => ({ ...current, recommendations: current.recommendations.filter((entry) => entry.id !== item.id) })) })}
      onScore={(score) => onChange((current) => setV2Score(current, item.id, score))}
      onTextFocus={() => setFocusItemId(null)}
      side={isSide(item)}
      onSide={(side) => setRole(item.id, side)}
    />
  );
  const counseling = criterion.kind === "counseling";
  const missed = criterionOmissionHarm(criterion);
  const missedLabel = missed === "inactive" ? "None required" : missed ? SEVERITY_LABEL[missed] : "Not rated";
  const flagged = Boolean(criterion.unresolved || criterion.recommendations.some((item) => item.unresolved));
  const addItem = (): void => {
    const item = newV2Item(record, criterion);
    setFocusItemId(item.id);
    onChange((current) => ({ ...current, recommendations: [...current.recommendations, item] }));
  };
  return <Card
    closedPill={<>{flagged && <span className={flagClass}>Unresolved</span>}<span className={pillClass}>{missedLabel}</span></>}
    editableQuestion={criterion.kind === "plan" ? <AutoText aria-label={`Criterion ${criterion.id}`} className="text-[14.5px] font-bold" placeholder="Write what this criterion evaluates and any condition" value={criterion.question} onChange={(question) => onChange((current) => ({ ...current, question }))} /> : undefined}
    id={criterion.id} issues={issues} open={open}
    openControls={onRemove && <button aria-label={`Remove ${criterion.id}`} className={`${iconButton} hover:!bg-red-50 hover:!text-red-600 dark:hover:!bg-red-400/15 dark:hover:!text-red-300`} title="Remove this criterion" type="button" onClick={onRemove}><IconX /></button>}
    question={criterion.question} onToggle={onToggle}
  >
    <div data-v2-criterion={criterion.id} data-v2-kind={criterion.kind}>
      {criterion.unresolved && <div className="pl-[72px] pr-3 pt-2"><UnresolvedNote note={criterion.unresolved} /></div>}
      <RoleSections criterion={visible} isSide={isSide} rowFor={row} onRole={setRole}
        unaddressed={counseling ? undefined : <div data-row-grid data-unaddressed className={`${ROW_GRID} items-start py-1.5 text-[13.5px]`}>
          <NumberCell label={shortId(`${criterion.id}.0`)} />
          <p className="min-w-0 pt-0.5"><strong>Otherwise not adequately answered or addressed</strong>{(omission?.text ?? V2_OMISSION_TEXT).slice("Otherwise not adequately answered or addressed".length)}</p>
          <div data-score-cell>
            <div className={`rounded-md ${omission?.score == null ? UNRATED_RING : ""}`} data-unrated={omission?.score == null || undefined}><ScoreBar descriptions={V2_SCORE_DESCRIPTORS} label={`Score for ${criterion.id}.0`} value={omission?.score ?? null} onChange={(score) => setOmission({ score })} /></div>
          </div>
          <HoverTip text={V2_OMISSION_ERROR_HELP}>{(describedBy) => <div aria-describedby={describedBy} data-severity-cell>
            <V2HarmSelect label={`Error severity if ${criterion.id} is otherwise not adequately answered or addressed`} value={omission?.harm ?? null} onChange={(harm) => setOmission({ harm })} />
          </div>}</HoverTip>
          <span />
        </div>}
        omission={counseling
          ? <HoverTip text="The worst harm if missed among the required items below. It is computed, not rated here.">{(describedBy) => (
            <span aria-describedby={describedBy} className="inline-flex items-center gap-1.5" data-omission-slot="locked"><span>worst if missed</span><span aria-label={`Harm if ${criterion.id} is missed, from items: ${missedLabel}`} className={`${lockedPill} border border-dashed border-[hsl(var(--border))] ${missed && missed !== "inactive" ? harmTone(missed) : `bg-[hsl(var(--muted))]/40 ${muted}`}`} data-omission-locked tabIndex={0}>{missedLabel}</span></span>
          )}</HoverTip>
          : undefined} />
      {visible.recommendations.length === 0 && <p className={`pl-[72px] pt-1 text-xs ${muted}`}>No items yet.</p>}
      <div className="mt-1 flex items-center gap-1.5 border-t border-[hsl(var(--border))] bg-[hsl(var(--muted))]/35 py-1 pl-[72px] pr-3">
        <button aria-label={`Add an item to ${criterion.id}`} className={chipButton} data-add-v2-item={criterion.id} type="button" onClick={addItem}>+ Add</button>
      </div>
    </div>
  </Card>;
}

function TextV2Warnings({ warnings }: { warnings: string[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  // Below-floor severities (D147) may stay; unknown ratings and unresolved notes block scoring.
  const belowFloor = warnings.filter((warning) => warning.endsWith("(D147)")).length;
  return (
    <div className={`rounded-lg ${warnPanel}`} data-v2-warnings>
      <button aria-controls={id} aria-expanded={open} className="flex items-center gap-1.5 text-left font-semibold" type="button" onClick={() => setOpen((value) => !value)}>
        <Chevron open={open} />
        {warnings.length} draft warning{warnings.length === 1 ? "" : "s"}. Saving is allowed.
        {belowFloor < warnings.length && " Unknown ratings and unresolved notes must be settled before scoring."}
        {belowFloor > 0 && " A harm milder than a low score implies can stay if intended."}
      </button>
      <div className={`group-content-wrapper ${open ? "expanded" : ""}`} id={id} inert={!open ? true : undefined}>
        <div className="group-content-inner"><ul className="mt-1 list-disc space-y-0.5 pl-5">{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>
      </div>
    </div>
  );
}

export default function RubricEditor({ caseId, previewOnly = false, benchmarkRecord, tutorial, host }: { caseId: string; previewOnly?: boolean; benchmarkRecord?: TextV2Case; tutorial?: EditorTutorial; host?: TextV2EditorHost<LoadedV2> }) {
  const { reviewerId: storedReviewerId } = useReviewerId();
  const reviewerId = host ? host.reviewerId : storedReviewerId;
  const [removalRequest, setRemovalRequest] = useState<RemovalRequest | null>(null);
  const [removalOpen, setRemovalOpen] = useState(false);
  const requestRemoval = (request: RemovalRequest): void => { setRemovalRequest(request); setRemovalOpen(true); };
  // The tutorial brings its own record and never reads or writes a reviewer copy.
  const [v2, setV2] = useState<LoadedV2 | null>(() => tutorial ? { record: structuredClone(tutorial.record), source: tutorial.source, provenance: { source: tutorial.record, sourceFile: "", sourceRubricSha256: "" }, fromCopy: false } : host?.initial ?? null);
  const inTutorial = tutorial !== undefined;
  const [status, setStatus] = useState<SaveStatus>("clean");
  // Unsaved edits stay guarded after a failed save; only a successful save or a fresh load clears this.
  const [dirty, setDirty] = useState(false);
  // Separate from status: an edit during a save marks the draft dirty, and the next autosave waits for this one.
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("Loading...");
  const [openIds, setOpenIds] = useState<Set<string>>(() => new Set(host?.initial ? ["D0", ...host.initial.record.decisions.map((d) => d.id)] : []));
  const [panelOpen, setPanelOpen] = useState(false);
  const panelTrigger = useRef<HTMLButtonElement | null>(null);
  const closePanel = useCallback(() => setPanelOpen(false), []);
  const timing = useRef<AuthoringTiming | null>(null);
  // Counts edits so a save only clears the unsaved flag when nothing changed while it was in flight.
  const revision = useRef(0);
  // A host can call save directly (save and continue), so a save in flight refuses another rather than overlapping.
  const savePending = useRef(false);

  useEffect(() => {
    if (!reviewerId || inTutorial) return;
    setV2(null);
    (host ? host.load() : fetch(`/api/rubric?caseId=${encodeURIComponent(caseId)}&reviewer=${encodeURIComponent(reviewerId)}`, { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error ?? "Unable to load.");
        return body as LoadedV2;
      }))
      .then((data) => {
        timing.current = data.timing ? { ...data.timing, lastInteractionAt: new Date().toISOString() } : newTiming(new Date());
        // Preview only: a benchmark rewrite replaces the loaded record; previewOnly never saves it.
        const body = benchmarkRecord ? { ...data, record: structuredClone(benchmarkRecord) } : data;
        setOpenIds(new Set(["D0", ...body.record.decisions.map((d) => d.id)]));
        setV2(body);
        setStatus("clean");
        setDirty(false);
        setMessage(body.fromCopy ? `Loaded your saved copy (${reviewerId})` : "Loaded the rubric");
      })
      .catch((error: Error) => { setStatus("error"); setMessage(error.message); });
  }, [caseId, reviewerId, benchmarkRecord, inTutorial, host]);
  useEffect(() => { host?.onDirtyChange?.(dirty); }, [dirty, host]);
  useEffect(() => { host?.onSavingChange?.(saving); }, [saving, host]);

  useEffect(() => {
    const touch = (): void => { if (timing.current) timing.current = recordInteraction(timing.current, new Date()); };
    window.addEventListener("pointerdown", touch);
    window.addEventListener("keydown", touch);
    return () => { window.removeEventListener("pointerdown", touch); window.removeEventListener("keydown", touch); };
  }, []);

  useEffect(() => {
    if (previewOnly) return;
    const warn = (event: BeforeUnloadEvent): void => { if (dirty) event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, previewOnly]);

  const v2Check = useMemo(() => (v2 ? host ? host.validate(v2.record) : validateTextV2(v2.record, "draft") : null), [v2, host]);

  const updateV2 = useCallback((scope: string, change: (record: TextV2Case) => TextV2Case): void => {
    if (timing.current) timing.current = recordEdit(timing.current, scope, new Date());
    revision.current += 1;
    setV2((current) => current && { ...current, record: change(current.record) });
    setStatus("dirty");
    setDirty(true);
    setMessage("Unsaved changes");
  }, []);
  const updateV2Criterion = (criterionId: string, updater: (criterion: TextV2Criterion) => TextV2Criterion): void =>
    updateV2(criterionId, (record) => ({ ...record, decisions: record.decisions.map((d) => (d.id === criterionId ? updater(d) : d)) }));

  const setOpenList = useCallback((ids: string[]): void => setOpenIds(new Set(ids)), []);
  const updateTutorialRecord = useCallback((change: (record: TextV2Case) => TextV2Case): void => setV2((current) => current && { ...current, record: change(current.record) }), []);

  const toggle = (id: string): void => setOpenIds((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const save = async (): Promise<boolean> => {
    if (previewOnly || savePending.current) return false;
    if (!v2 || !reviewerId || !timing.current) return false;
    savePending.current = true;
    setSaving(true);
    const submitted = revision.current;
    try {
      if (host) {
        let saved: Awaited<ReturnType<typeof host.save>>;
        try { saved = await host.save(v2, timing.current); } catch (error) { setStatus("error"); setMessage(`Save failed: ${(error as Error).message}`); return false; }
        if (saved.update) setV2((current) => current && { ...current, ...saved.update });
        if (revision.current !== submitted) { setStatus("dirty"); setMessage("Unsaved changes"); return false; }
        setStatus("saved");
        setDirty(false);
        setMessage(saved.message);
        host.onSaved?.();
        return true;
      }
      const response = await fetch("/api/rubric", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ caseId, reviewer: reviewerId, record: v2.record, provenance: v2.provenance, timing: timing.current }),
      });
      const body = await response.json();
      if (!response.ok) { setStatus("error"); setMessage(`Save failed: ${body.error}`); return false; }
      if (revision.current !== submitted) { setStatus("dirty"); setMessage("Unsaved changes"); return false; }
      setStatus("saved");
      setDirty(false);
      setMessage("All changes saved");
      return true;
    } finally {
      savePending.current = false;
      setSaving(false);
    }
  };
  const canSave = !(previewOnly || saving || !v2Check || v2Check.errors.length > 0 || (v2 !== null && host?.canSave?.(v2) === false));
  useRubricEditorHost({ dirty, saving, canSave, error: status === "error" ? message : null, save });

  // Saves once edits pause. A failed save waits for the next edit rather than retrying in a loop, and a draft with
  // errors waits until they are fixed, as the server would refuse it.
  const blocked = dirty && !!v2Check && v2Check.errors.length > 0;
  useEffect(() => {
    if (previewOnly || !reviewerId || !dirty || saving || status === "error" || blocked || !canSave || host?.saveLabel) return;
    const timer = setTimeout(() => { void save(); }, AUTOSAVE_MS);
    return () => clearTimeout(timer);
    // save reads the current record; v2Check changes with every edit, which restarts the wait.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blocked, canSave, dirty, previewOnly, reviewerId, saving, status, v2Check]);

  // Reset brings back the current original rubric, and autosave then replaces the reviewer's copy with it.
  const reset = async (): Promise<void> => {
    if (tutorial) { setV2((current) => current && { ...current, record: structuredClone(tutorial.record) }); return; }
    if (!reviewerId) return;
    let original: LoadedV2;
    if (host) {
      try { original = await host.loadOriginal(); } catch (error) { setStatus("error"); setMessage(`Reset failed: ${(error as Error).message}`); return; }
    } else {
      const response = await fetch(`/api/rubric?caseId=${encodeURIComponent(caseId)}&reviewer=${encodeURIComponent(reviewerId)}&original=1`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) { setStatus("error"); setMessage(`Reset failed: ${body.error}`); return; }
      original = body as LoadedV2;
    }
    if (timing.current) timing.current = recordEdit(timing.current, "reset", new Date());
    revision.current += 1;
    setOpenIds(new Set(["D0", ...original.record.decisions.map((d) => d.id)]));
    setV2(original);
    setStatus("dirty");
    setDirty(true);
    setMessage("Unsaved changes");
  };

  const allOpen = v2 ? openIds.has("D0") && v2.record.decisions.every((d) => openIds.has(d.id)) : false;
  const unratedCount = v2 ? unratedV2Count(v2.record) : 0;
  // The tutorial's only error is its new row, empty for a moment before its text writes itself in; showing it would
  // flash a banner and an issue count that push the page down and back.
  const shownErrors = inTutorial ? [] : v2Check?.errors ?? [];

  const toolButtons = v2 && <nav aria-label="Rubric tools" className="flex items-center gap-1">
    <button aria-controls="rubric-panel" aria-expanded={panelOpen} aria-haspopup="dialog" className={guideButton} onClick={(event) => { panelTrigger.current = event.currentTarget; setPanelOpen(true); }} type="button">Guide</button>
    {/* A new tab keeps this rubric, and any unsaved changes, where they are. */}
    {!inTutorial && <button aria-haspopup="dialog" className={headerButton} data-open-tutorial type="button" onClick={() => requestRemoval({
      title: "Tutorial",
      text: "We'll take you to a walkthrough tutorial with an example case.",
      detail: "It opens in a new tab, so this rubric and any unsaved changes stay as they are. Nothing in the tutorial is saved.",
      confirmLabel: "Open tutorial",
      focusAfterRemove: "[data-open-tutorial]",
      onConfirm: () => window.open(host?.tutorialHref ?? "/tutorial", "_blank", "noopener"),
    })}>Tutorial</button>}
  </nav>;

  return (
    <>
    <div className={`${panelStyles.editor} ${editorStyles.root}`} data-rubric inert={panelOpen ? true : undefined}>
    <div className="page-transition">
      <div className={panelStyles.page}>
        <header className="sticky top-0 z-40 -mt-3 mb-4 flex min-h-13 flex-wrap items-center justify-between gap-3 border-b border-[hsl(var(--border))]/50 bg-[hsl(var(--background))]/95 py-2.5 backdrop-blur">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            {host ? <span className="text-[15px] font-bold">NOHARM Rubric Editor</span> : <a className="text-[15px] font-bold text-[hsl(var(--foreground))]" href="/">NOHARM Rubric Editor</a>}
            <span className="text-sm font-semibold">{caseId}</span>
            {host?.headerTags?.(v2)}
            <div className="ml-6">{toolButtons}</div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span aria-live="polite" className={`text-xs ${status === "dirty" ? "font-medium text-amber-700 dark:text-amber-300" : status === "saved" ? "font-medium text-green-700 dark:text-green-400" : status === "error" ? "font-medium text-red-600 dark:text-red-400" : "text-gray-500 dark:text-gray-400"}`}>{inTutorial ? "Tutorial: edits are not saved" : previewOnly ? "Design preview: edits are not saved" : reviewerId ? (saving ? "Saving..." : blocked && status !== "error" ? "Not saved: some items need attention" : message) : ""}</span>
            {host?.saveLabel && <button className="rounded-md bg-[hsl(var(--primary))] px-3.5 py-1.5 text-xs font-bold text-[hsl(var(--primary-foreground))] shadow-sm transition-colors hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50" disabled={!canSave} type="button" onClick={() => { void save(); }}>
              {saving ? "Saving..." : host.saveLabel}
            </button>}
            {v2 && <button aria-haspopup="dialog" className={headerButton} data-reset-rubric type="button" onClick={() => requestRemoval({
              title: "Reset",
              text: inTutorial ? "Return the example to how it started?" : "Discard your changes and return to the original rubric?",
              detail: inTutorial ? "Nothing in the tutorial is saved." : "Your saved copy is replaced with the original. This cannot be undone.",
              confirmLabel: "Reset",
              focusAfterRemove: "[data-reset-rubric]",
              onConfirm: () => { void reset(); },
            })}>Reset</button>}
          </div>
        </header>

        {reviewerId && !v2 && <p className={status === "error" ? "text-red-600 dark:text-red-400" : `text-sm ${muted}`}>{message}</p>}

        {v2 && host?.banner?.(v2)}
        {v2?.sourceChanged && <p className={`mb-3 rounded-lg ${warnPanel}`} data-source-changed role="status">Your saved copy started from an earlier version of this rubric. It keeps your edits but not the changes made since.</p>}
        {/* The tutorial's amber outlines already mark the rows it leaves unrated on purpose. */}
        {!inTutorial && unratedCount > 0 && <p className="mb-3 text-xs text-amber-800 dark:text-amber-300" data-unrated-warning>{unratedCount} item{unratedCount === 1 ? " needs" : "s need"} ratings. Unrated items remain marked below.</p>}
        {v2 && v2Check && (
          <div className={panelStyles.workspace} data-rubric-text-v2>
            <CaseSourcePanel compact presentation={v2.source.presentation} recommendations={v2.source.recommendations} />
            <div className="min-w-0 space-y-2" data-v2-criteria>
              {shownErrors.length > 0 && (
                <div className="rounded-lg border border-orange-200 bg-orange-50 px-3.5 py-2 text-[12.5px] text-orange-900 dark:border-orange-400/30 dark:bg-orange-400/10 dark:text-orange-200" role="alert">
                  <strong>{shownErrors.length} item{shownErrors.length === 1 ? " needs" : "s need"} attention before saving</strong>
                  {shownErrors.length === 1
                    ? <span className="ml-2">{shownErrors[0]}</span>
                    : <ul className="mt-1 list-disc space-y-0.5 pl-5">{shownErrors.map((error) => <li key={error}>{error}</li>)}</ul>}
                </div>
              )}
              {/* The tutorial leaves rows unrated on purpose and never scores, so its draft warnings would only distract. */}
              {!inTutorial && v2Check.warnings.length > 0 && <TextV2Warnings warnings={v2Check.warnings} />}
              <div className={editorStyles.rubricToolbar} data-rubric-toolbar>
                <h1 className="text-base font-bold">Criteria</h1>
                <button className={editorStyles.disclosureButton} type="button" aria-label={allOpen ? "Collapse all rubric sections" : "Expand all rubric sections"} onClick={() => setOpenIds(allOpen ? new Set() : new Set(["D0", ...v2.record.decisions.map((d) => d.id)]))}>
                  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d={allOpen ? "m6 3 4 4 4-4M6 17l4-4 4 4" : "m6 7 4-4 4 4M6 13l4 4 4-4"} />
                  </svg>
                  {allOpen ? "Collapse all" : "Expand all"}
                </button>
              </div>
              {v2.record.unresolved && <UnresolvedNote note={v2.record.unresolved} />}
              <UsualCareCard issues={shownErrors.filter((e) => e.startsWith("usualCare") || e.startsWith("case: usualCare"))} open={openIds.has("D0")} value={v2.record.usualCare ?? { harm: null }} onChange={(usualCare) => updateV2("D0", (record) => ({ ...record, usualCare }))} onToggle={() => toggle("D0")} />
              {v2.record.decisions.map((criterion) => (
                <TextV2CriterionCard
                  criterion={criterion}
                  issues={v2Issues(criterion, shownErrors)}
                  key={`${caseId}:${criterion.id}`}
                  open={openIds.has(criterion.id)}
                  record={v2.record}
                  onChange={(updater) => updateV2Criterion(criterion.id, updater)}
                  onRemove={criterion.kind !== "plan" ? undefined : () => requestRemoval({
                    title: `Remove criterion ${criterion.id}?`,
                    text: criterion.question || "Untitled Criterion",
                    detail: "This also removes all items in this criterion.",
                    focusAfterRemove: "[data-rubric-toolbar] button",
                    onConfirm: () => updateV2(criterion.id, (record) => ({ ...record, decisions: record.decisions.filter((d) => d.id !== criterion.id) })),
                  })}
                  onRequestRemoval={requestRemoval}
                  onToggle={() => toggle(criterion.id)}
                />
              ))}
              <div className="px-0.5">
                <button className={`${chipButton} px-2.5 py-1 text-xs`} data-add-criterion type="button" onClick={() => {
                  const { added } = addV2Criterion(v2.record);
                  updateV2(added, (record) => addV2Criterion(record).record);
                  setOpenIds((current) => new Set(current).add(added));
                }}>+ Criterion</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
      {/* Outside the slide-up wrapper, whose transform would pin this fixed panel to the page. */}
      {v2 && <RubricPanel open={panelOpen} trigger={panelTrigger.current} onClose={closePanel} />}
    </div>
    {removalRequest && <RemovalDialog request={removalRequest} open={removalOpen} onClose={() => setRemovalOpen(false)} />}
    {tutorial && v2 && tutorial.overlay({ record: v2.record, openIds, setOpenIds: setOpenList, updateRecord: updateTutorialRecord })}
    </>
  );
}

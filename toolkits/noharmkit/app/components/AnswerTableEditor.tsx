"use client";

import { useRouter } from "next/navigation";
import { Fragment, createContext, useContext, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";

import CompactRecommendationTags from "./CompactRecommendationTags";
import OnlyIfCondition from "./OnlyIfPreview";
import tagStyles from "./CompactRecommendationTags.module.css";
import RemovalDialog, { type RemovalRequest } from "./RemovalDialog";
import AnswerTablePanel from "@/components/AnswerTablePanel";
import editorStyles from "./AnswerTableEditor.module.css";
import type { GuideColorAppearance, GuideSections } from "./QuickAuthoringGuide";
import type { ReactNode } from "react";
import { ReviewTag } from "@/components/mc/ui";
import type { ReviewState } from "@/lib/caseset/reviews";
import type { AnswerTablePanelView } from "@/components/AnswerTablePanel";
import panelStyles from "./AnswerTablePanel.module.css";
import CaseSourcePanel from "@/components/CaseSourcePanel";
import Dropdown from "@/components/Dropdown";
import {
  addDecision,
  bestScore,
  delayHarm,
  derivedDelayHarm,
  derivedHarmIfRecommended,
  derivedNeedSeverity,
  derivedRelativeHarm,
  groupByScore,
  groupedRows,
  HARM_LEVELS,
  harmIfRecommended,
  insertInGroup,
  needSeverity,
  newTiming,
  nextRowId,
  recordEdit,
  recordInteraction,
  relativeHarm,
  removeDecision,
  SCORE_DESCRIPTORS,
  setRowScore,
  USUAL_CARE_DEFINITION,
  USUAL_CARE_QUESTION,
  validateAnswerTable,
} from "@/lib/answer-table";
import type {
  AnswerDecision,
  AnswerTableCase,
  AuthoringTiming,
  GroupOf,
  NeedSeverity,
  Recommendation,
  RowGroup,
  RowHarm,
  Score,
  Timing,
  UsualCare,
} from "@/lib/answer-table";
import { useReviewerId } from "@/lib/reviewer-id";
import type { CaseSource } from "@/lib/types";
import { FailedErrors, FailedTag } from "@/components/runs/VersionFailure";
import { savedNotice } from "@/lib/caseset/notice";
import type { CommitteeRatings, RatingItem } from "@/lib/caseset/types";
import { useRubricEditorHost } from "@/components/RubricEditorHost";

export interface CasesetSource { caseset: string; version: string }
const CourseLogicPreview = createContext(false);

type SaveStatus = "clean" | "dirty" | "saving" | "saved" | "error";

export interface Loaded<Record = AnswerTableCase> {
  record: Record;
  source: CaseSource;
  timing?: AuthoringTiming;
  savedAt?: string;
  fromCopy: boolean;
  notice?: string;
  ratings?: CommitteeRatings | null;
  status?: "pass" | "failed";
  errors?: string[];
  canSave?: boolean;
  cannotSaveReason?: string;
  sourceSha256?: string | null;
  replacesSha256?: string | null;
}

const SEVERITIES: NeedSeverity[] = ["none", "mild", "moderate", "severe"];
const TIMINGS: Timing[] = ["emergency", "urgent", "routine", "none"];
const TIMING_LABEL: Record<Timing, string> = { emergency: "Emergency", urgent: "Urgent", routine: "Routine", none: "No set timing" };
const SEVERITY_LABEL: Record<NeedSeverity, string> = { none: "None", mild: "Mild", moderate: "Moderate", severe: "Severe" };
const SCORES: Score[] = [1, 2, 3, 4, 5, 6, 7, 8, 9];

const ROW_GRID = "grid grid-cols-[36px_90px_minmax(0,1fr)_194px_204px_60px]";
const muted = "text-[hsl(var(--muted-foreground))]";
const smallSelect = "h-7 rounded-md border px-1.5 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]/40";
const textButton = "rounded px-1 py-0.5 text-xs font-semibold text-[hsl(var(--primary))] transition-colors hover:bg-[hsl(var(--primary))]/10";
const chipClass = "inline-flex items-center gap-1 rounded-full border border-[hsl(var(--border))] bg-white px-2 py-px text-xs text-[hsl(var(--foreground))]";
// Neutral chip for adding rows and Decisions (design canvas Round 3, option C).
const chipButton = "rounded border border-[hsl(var(--border))] bg-white px-2 py-0.5 text-[11px] font-semibold text-[hsl(var(--foreground))] transition-colors hover:border-[hsl(var(--primary))]/50 hover:bg-[hsl(var(--primary))]/5";
const iconButton = "inline-flex h-6 w-6 items-center justify-center rounded text-[hsl(var(--muted-foreground))]/70 transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]";

function shortId(id: string): string {
  return id.replace(/^D/, "").replace(".O", ".");
}

function rowText(record: AnswerTableCase, rowId: string): string {
  for (const d of record.decisions) {
    const row = d.recommendations.find((r) => r.id === rowId);
    if (row) return row.text || rowId;
  }
  return rowId;
}

function decisionIssues(decision: AnswerDecision, errors: string[]): string[] {
  const label = `${decision.question.trim() || decision.id}:`;
  return errors.filter((e) => e.startsWith(label));
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

function IconPlus() {
  return (
    <svg aria-hidden="true" className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path d="M12 5v14M5 12h14" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} />
    </svg>
  );
}

function IconCondition(): ReactNode {
  return <svg aria-hidden="true" className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path d="M5 4v12a4 4 0 0 0 4 4h10M5 8h14m-4-4 4 4-4 4m0 4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} />
  </svg>;
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
      className={`-mx-1.5 block w-[calc(100%+0.75rem)] resize-none! overflow-hidden rounded bg-transparent px-1.5 py-0.5 leading-5 text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]/70 transition-colors hover:bg-[hsl(var(--muted))]/60 focus:bg-white ${className}`}
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

interface MenuItem { key: string; label: string; onSelect: () => void }

function DetailToggle({ label, open, disabled, onToggle }: { label: string; open: boolean; disabled: boolean; onToggle: () => void }) {
  if (disabled) return <span className="w-6" />;
  return (
    <button aria-expanded={open} aria-label={label} data-row-action className={`${iconButton} ${open ? "bg-[hsl(var(--muted))] !text-[hsl(var(--foreground))]" : ""}`} title="Add a detail" type="button" onClick={onToggle}>
      <IconPlus />
    </button>
  );
}

// Inline rather than a popover: the collapsible card clips anything that overflows it.
function DetailOptions({ open, items, onDone }: { open: boolean; items: MenuItem[]; onDone: () => void }) {
  const shown = open && items.length > 0;
  return (
    <div className={`group-content-wrapper ${shown ? "expanded" : ""}`} inert={!shown ? true : undefined}>
      <div className="group-content-inner">
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <span className={`text-[11px] ${muted}`}>Add</span>
          {items.map((item) => <button className={textButton} key={item.key} type="button" onClick={() => { item.onSelect(); onDone(); }}>{item.label}</button>)}
        </div>
      </div>
    </div>
  );
}

function ChipList({
  label,
  items,
  placeholder,
  autoFocus,
  onChange,
}: {
  label: string;
  items: string[];
  placeholder: string;
  autoFocus: boolean;
  onChange: (items: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = (): void => {
    const values = draft.split(/[,;\n]/).map((v) => v.trim()).filter((v) => v && !items.includes(v));
    if (values.length) onChange([...items, ...new Set(values)]);
    setDraft("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-relationship-group={label === "Must include" ? "parts" : "alternatives"}>
      <span className={`mr-0.5 text-[11px] ${muted}`} data-relationship-label>{label}</span>
      {items.map((item) => (
        <span className={chipClass} data-relationship-item key={item}>
          {item}
          <button aria-label={`Remove ${item}`} className={`${muted} hover:text-red-600`} type="button" onClick={() => onChange(items.filter((x) => x !== item))}>×</button>
        </span>
      ))}
      <input
        aria-label={`Add to ${label}`}
        data-relationship-entry
        autoFocus={autoFocus}
        className="w-52 rounded-full border border-dashed border-[hsl(var(--border))] bg-transparent px-2 py-px text-xs focus:border-[hsl(var(--primary))] focus:outline-none"
        placeholder={placeholder}
        value={draft}
        onBlur={add}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }}
      />
    </div>
  );
}

// Red (1) to blue (9) through neutral. Static class strings so Tailwind keeps them.
const SCORE_FILL: Record<Score, string> = {
  1: "bg-[#b91c1c] text-white", 2: "bg-[#dc2626] text-white", 3: "bg-[#f87171] text-red-950",
  4: "bg-[#fecaca] text-red-950", 5: "bg-[#d6d3d1] text-stone-900", 6: "bg-[#bfdbfe] text-blue-950",
  7: "bg-[#60a5fa] text-blue-950", 8: "bg-[#2563eb] text-white", 9: "bg-[#1e40af] text-white",
};
const SCORE_TINT: Record<Score, string> = {
  1: "bg-[#f1d2d2] text-red-900/70", 2: "bg-[#f8d4d4] text-red-900/70", 3: "bg-[#fee3e3] text-red-900/70",
  4: "bg-[#fff1f1] text-red-900/60", 5: "bg-[#f5f4f3] text-stone-600", 6: "bg-[#eff6ff] text-blue-900/60",
  7: "bg-[#dfedfe] text-blue-900/70", 8: "bg-[#d3e0fb] text-blue-900/70", 9: "bg-[#d2d9ef] text-blue-900/70",
};

// Both controls share one score; the Decision's width determines which is visible.
function ScoreBar({ label, value, onChange }: { label: string; value: Score | null; onChange: (score: Score) => void }) {
  // The tooltip keeps its last position while fading out.
  const [tip, setTip] = useState<{ score: Score; x: number; y: number; visible: boolean } | null>(null);
  const show = (score: Score, el: HTMLElement): void => {
    const r = el.getBoundingClientRect();
    setTip({ score, x: r.left + r.width / 2, y: r.top, visible: true });
  };
  const hide = (): void => setTip((t) => t && { ...t, visible: false });
  const describe = (s: Score): string => SCORE_DESCRIPTORS[s];
  return (
    <div data-score-control>
    <div data-score-dropdown>
      <HoverTip text={value === null ? "Choose an appropriateness score from 1 to 9." : describe(value)}>{(describedBy) => (
        <Dropdown aria-label={label} aria-describedby={describedBy} className={smallSelect} value={value ?? ""} onChange={(event) => { if (event.target.value) onChange(Number(event.target.value) as Score); }}>
          <option value="" disabled>Rate</option>
          {SCORES.map((s) => <option key={s} value={s}>{s}</option>)}
        </Dropdown>
      )}</HoverTip>
    </div>
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
            onClick={() => onChange(s)}
            onFocus={(event) => show(s, event.currentTarget)}
            onMouseEnter={(event) => show(s, event.currentTarget)}
          >
            {s}
          </button>
        );
      })}
      <div
        aria-hidden="true"
        className={`pointer-events-none fixed z-50 w-64 -translate-x-1/2 -translate-y-full rounded-md bg-[hsl(var(--foreground))] px-2.5 py-1.5 text-[11.5px] leading-snug text-white shadow-lg transition-opacity duration-150 motion-reduce:transition-none ${tip?.visible ? "opacity-100" : "opacity-0"}`}
        style={tip ? { left: tip.x, top: tip.y - 6 } : { left: -9999, top: -9999 }}
      >
        {tip && describe(tip.score)}
      </div>
    </div>
    </div>
  );
}

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
        className={`pointer-events-none fixed z-50 w-64 -translate-x-1/2 -translate-y-full rounded-md bg-[hsl(var(--foreground))] px-2.5 py-1.5 text-[11.5px] leading-snug text-white shadow-lg transition-opacity duration-150 motion-reduce:transition-none ${tip?.visible ? "opacity-100" : "opacity-0"}`}
        id={id}
        role="tooltip"
        style={tip ? { left: tip.x, top: tip.y - 6 } : { left: -9999, top: -9999 }}
      >
        {text}
      </div>
    </div>
  );
}

// Harm of a row. Locked in combined mode; in dual mode a dropdown whose default is the derived value.
function harmTone(harm: RowHarm): string {
  return harm === "uncertain" || harm === "none" ? "bg-mc-surface-2 text-mc-ink" : harm === "mild" ? "bg-amber-50 text-amber-900" : "bg-orange-50 text-orange-900";
}

function HarmCell({ label, help, derived, value, suffix, allowUncertain, onChange }: {
  label: string;
  help: string;
  derived: RowHarm | null;
  value: RowHarm | null;
  suffix: string;
  allowUncertain: boolean;
  onChange: (override: NeedSeverity | undefined) => void;
}) {
  if (derived === null) return <span />;
  const text = (h: RowHarm): string => h === "uncertain" ? "Uncertain" : `${SEVERITY_LABEL[h]} ${suffix}`.trim();
  const shown = value ?? derived;
  const tip = [
    shown === "none" ? "None: nothing is charged." : "",
    help,
    shown !== derived ? `Overridden; the default is ${text(derived)}.` : "",
  ].filter(Boolean).join(" ");
  const options: RowHarm[] = [...(allowUncertain ? ["uncertain" as const] : []), ...HARM_LEVELS];
  return (
    <HoverTip text={tip}>{(describedBy) => (
      <Dropdown
        aria-describedby={describedBy}
        aria-label={label}
        className={`h-7 w-full rounded-md border px-1.5 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]/40 ${shown !== derived ? "border-violet-400" : "border-[hsl(var(--border))]"} ${harmTone(shown)}`}
        value={shown}
        onChange={(event) => { const next = event.target.value as RowHarm; onChange(next === derived ? undefined : (next as NeedSeverity)); }}
      >
        {options.map((h) => <option key={h} value={h}>{text(h)}{h === derived ? " (default)" : ""}</option>)}
      </Dropdown>
    )}</HoverTip>
  );
}

function AppropriateRow({
  row,
  decision,
  others,
  onChange,
  onScore,
  onRemove,
  autoFocus,
  onTextFocus,
}: {
  row: Recommendation;
  decision: AnswerDecision;
  others: AnswerDecision[];
  onChange: (patch: Partial<Recommendation>) => void;
  onScore: (score: Score) => void;
  onRemove: () => void;
  autoFocus: boolean;
  onTextFocus: () => void;
}) {
  const courseLogic = useContext(CourseLogicPreview);
  const followUp = decision.kind === "followUp";
  const [opened, setOpened] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const showEq = Boolean(row.equivalents?.length) || opened === "eq";
  const showParts = Boolean(row.parts?.length) || opened === "parts";
  const showCovers = Boolean(row.alsoTakesCareOf?.length) || opened === "covers";
  const menu: MenuItem[] = [
    ...(!showEq ? [{ key: "eq", label: "Equivalent alternatives", onSelect: () => setOpened("eq") }] : []),
    ...(!showParts ? [{ key: "parts", label: "Must include", onSelect: () => setOpened("parts") }] : []),
    ...(!showCovers && others.length ? [{ key: "covers", label: "Also takes care of", onSelect: () => setOpened("covers") }] : []),
  ];
  const best = bestScore(decision);
  const isBest = row.score !== null && row.score === best;
  const tied = isBest && decision.recommendations.filter((r) => r.score === best).length > 1;
  const role = row.score === null
    ? <span className={`block pt-0.5 text-xs font-bold leading-5 ${muted}`}>Unscored</span>
    : <span className="block pt-0.5 text-xs font-bold leading-5 text-blue-800">Appropriate</span>;
  return (
    <div data-row-grid className={`${ROW_GRID} items-start py-1.5 text-[13.5px]`}>
      <div className={`pl-3 pt-0.5 text-[11px] leading-5 ${muted} ${tagStyles.rowMeta}`}><span>{shortId(row.id)}</span><CompactRecommendationTags row={row} onChange={(tags) => onChange({ tags })} /></div>
      <div>{role}</div>
      <div className="min-w-0">
        <div className={tagStyles.recommendation}>
          <AutoText autoFocus={autoFocus} onFocus={onTextFocus} aria-label={`Recommendation ${row.id}`} placeholder={followUp ? "A referral, escalation of care, or reassessment" : "What the response recommends"} value={row.text} onChange={(text) => onChange({ text })} />
        </div>
        {followUp && (
          <div className="mt-1 flex items-center gap-1.5">
            <label className={`text-[11px] ${muted}`} htmlFor={`${row.id}-timing`}>Timing</label>
            <Dropdown className={`${smallSelect} ${row.timing ? "" : "border-amber-400 bg-amber-50 text-amber-800"}`} id={`${row.id}-timing`} value={row.timing ?? ""} onChange={(event) => onChange({ timing: (event.target.value || undefined) as Timing | undefined })}>
              <option value="">Choose timing</option>
              {TIMINGS.map((t) => <option key={t} value={t}>{TIMING_LABEL[t]}</option>)}
            </Dropdown>
          </div>
        )}
        <DetailOptions items={menu} open={menuOpen} onDone={() => setMenuOpen(false)} />
        {(showEq || showParts || showCovers) && (
          <div className="mt-1.5 space-y-1.5">
            {showEq && <ChipList autoFocus={opened === "eq"} items={row.equivalents ?? []} label="Equivalent alternatives" placeholder="Add alternative, then Enter" onChange={(items) => onChange({ equivalents: items.length ? items : undefined })} />}
            {showParts && (courseLogic ? <div className="rounded-md border border-[hsl(var(--border))] p-2" data-course-actions>
              <p className={`mb-2 text-[11px] font-semibold ${muted}`}>Complete course: all actions required</p>
              {(row.parts ?? []).map((part, index) => <div key={index}>
                {index > 0 && <p className={`my-1 text-center text-[11px] font-bold ${muted}`}>AND</p>}
                <AutoText aria-label={`Action ${index + 1} of ${row.id}`} value={part} placeholder="Required action" onChange={(text) => onChange({ parts: row.parts!.map((item, i) => i === index ? text : item) })} />
              </div>)}
              <button className={`${chipButton} mt-2`} type="button" onClick={() => onChange({ parts: [...(row.parts ?? []), ""] })}>+ AND action</button>
            </div> : <ChipList autoFocus={opened === "parts"} items={row.parts ?? []} label="Must include" placeholder="Add needed item" onChange={(items) => onChange({ parts: items.length ? items : undefined })} />)}
            {showCovers && (
              <div className="flex flex-wrap items-center gap-1.5" data-relationship-group="coverage">
                <span className={`mr-0.5 text-[11px] ${muted}`} data-relationship-label>Also takes care of</span>
                {(row.alsoTakesCareOf ?? []).map((id) => (
                  <span className={chipClass} data-relationship-item key={id}>
                    {id}: {others.find((d) => d.id === id)?.question || id}
                    <button aria-label={`Remove ${id}`} className={`${muted} hover:text-red-600`} type="button" onClick={() => { const next = (row.alsoTakesCareOf ?? []).filter((x) => x !== id); onChange({ alsoTakesCareOf: next.length ? next : undefined }); }}>×</button>
                  </span>
                ))}
                <Dropdown data-relationship-entry aria-label="Add a Decision this recommendation takes care of" className={`${smallSelect} font-normal`} value="" onChange={(event) => { if (event.target.value) onChange({ alsoTakesCareOf: [...(row.alsoTakesCareOf ?? []), event.target.value] }); }}>
                  <option value="">Choose a Decision</option>
                  {others.filter((d) => !(row.alsoTakesCareOf ?? []).includes(d.id)).map((d) => <option key={d.id} value={d.id}>{d.id}: {d.question}</option>)}
                </Dropdown>
              </div>
            )}
          </div>
        )}
      </div>
      <ScoreBar label={`Score for ${row.id}`} value={row.score} onChange={onScore} />
      {isBest
        ? (
          <HoverTip text={tied ? "Tied for best. Any one equivalent alternative is sufficient: a response that gives one of them meets this Decision." : "The best option: a response that gives it meets this Decision. Its score suggests the default harm of omission; judge plausible harm separately."}>
            {(describedBy) => <span aria-describedby={describedBy} className={`${lockedPill} bg-blue-50 text-blue-800`} tabIndex={0}>{tied ? "No harm (equivalent best)" : "No harm (best option)"}</span>}
          </HoverTip>
        )
        : <HarmCell allowUncertain={derivedRelativeHarm(decision, row) === "uncertain"} derived={derivedRelativeHarm(decision, row)} help="Choosing this instead of the best option earns partial credit, plus this harm. The default uses the score gap (1 point Mild, 2 points Moderate), capped one step below Unaddressed. Choose the plausible harm for this case." label={`Relative harm of ${row.id}`} suffix="vs best" value={relativeHarm(decision, row)} onChange={(relativeHarmOverride) => onChange({ relativeHarmOverride })} />}
      <div className="flex items-center justify-end gap-0.5 pr-2">
        <DetailToggle disabled={!menu.length} label={`Add a detail to ${row.id}`} open={menuOpen} onToggle={() => setMenuOpen((v) => !v)} />
        <button aria-label={`Remove ${row.id}`} data-row-action className={`${iconButton} hover:!bg-red-50 hover:!text-red-600`} title="Remove" type="button" onClick={onRemove}><IconX /></button>
      </div>
    </div>
  );
}

// A row scored 1-6 (tagged Inappropriate for 1-3, Uncertain for 4-6).
function NotAppropriateRow({
  row,
  appropriate,
  onChange,
  onScore,
  onRemove,
  autoFocus,
  onTextFocus,
}: {
  row: Recommendation;
  appropriate: Recommendation[];
  onChange: (patch: Partial<Recommendation>) => void;
  onScore: (score: Score) => void;
  onRemove: () => void;
  autoFocus: boolean;
  onTextFocus: () => void;
}) {
  const [opened, setOpened] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const bundles = appropriate.filter((r) => r.parts?.length);
  const showIncomplete = Boolean(row.incompleteVersionOf) || opened;
  const menu: MenuItem[] = bundles.length && !showIncomplete ? [{ key: "incomplete", label: "Incomplete version of", onSelect: () => setOpened(true) }] : [];
  const role = row.score === null ? ["Unscored", muted] : row.score <= 3 ? ["Inappropriate", "text-orange-800"] : ["Uncertain", "text-stone-600"];
  return (
    <div data-row-grid className={`${ROW_GRID} items-start py-1.5 text-[13.5px]`}>
      <div className={`pl-3 pt-0.5 text-[11px] leading-5 ${muted} ${tagStyles.rowMeta}`}><span>{shortId(row.id)}</span><CompactRecommendationTags row={row} onChange={(tags) => onChange({ tags })} /></div>
      <div><span className={`pt-0.5 text-xs font-bold leading-5 ${role[1]}`}>{role[0]}</span></div>
      <div className="min-w-0">
        <div className={tagStyles.recommendation}>
          <AutoText autoFocus={autoFocus} onFocus={onTextFocus} aria-label={`Inappropriate recommendation ${row.id}`} placeholder="What a response might say instead" value={row.text} onChange={(text) => onChange({ text })} />
        </div>
        <DetailOptions items={menu} open={menuOpen} onDone={() => setMenuOpen(false)} />
        {showIncomplete && (
          <div className="mt-1.5 flex items-center gap-1.5" data-relationship-group="incomplete">
            <label data-relationship-label className={`text-[11px] ${muted}`} htmlFor={`${row.id}-incomplete`}>Incomplete version of</label>
            <Dropdown data-relationship-entry autoFocus={opened && !row.incompleteVersionOf} className={`${smallSelect} font-normal`} id={`${row.id}-incomplete`} value={row.incompleteVersionOf ?? ""} onChange={(event) => { onChange({ incompleteVersionOf: event.target.value || undefined }); if (!event.target.value) setOpened(false); }}>
              <option value="">No</option>
              {bundles.map((r) => <option key={r.id} value={r.id}>{shortId(r.id)}: {r.text}</option>)}
            </Dropdown>
          </div>
        )}
      </div>
      <ScoreBar label={`Score for ${row.id}`} value={row.score} onChange={onScore} />
      <HarmCell allowUncertain={derivedHarmIfRecommended(row) === "uncertain"} derived={derivedHarmIfRecommended(row)} help={row.score !== null && row.score >= 4 ? "Default for scores 4-6: Uncertain, an uncertain-harm event below Mild. Choose the plausible harm if recommended, separately from any unmet need." : "Harm if this is recommended, in addition to any unmet need. Defaults: 1 Severe, 2 Moderate, 3 Mild. Choose the plausible harm for this case."} label={`Harm if ${row.id} is recommended`} suffix="if recommended" value={harmIfRecommended(row)} onChange={(harmIfRecommendedOverride) => onChange({ harmIfRecommendedOverride })} />
      <div className="flex items-center justify-end gap-0.5 pr-2">
        <DetailToggle disabled={!menu.length} label={`Add a detail to ${row.id}`} open={menuOpen} onToggle={() => setMenuOpen((v) => !v)} />
        <button aria-label={`Remove ${row.id}`} data-row-action className={`${iconButton} hover:!bg-red-50 hover:!text-red-600`} title="Remove" type="button" onClick={onRemove}><IconX /></button>
      </div>
    </div>
  );
}

// The rows of one Decision: appropriate recommendations (any one is enough), then 1-6 ones.
// The two fixed plans at the end of every Decision: a delay and no appropriate recommendation.
function SpecialRow({ id, role, text, derivedNote, children }: { id?: string; role: string; text: string; derivedNote: string; children: React.ReactNode }) {
  return (
    <div data-row-grid data-special-row={role} className={`${ROW_GRID} items-start border-t border-[hsl(var(--border))]/60 bg-[hsl(var(--muted))]/30 py-1.5 text-[13.5px]`}>
      <span className={`pl-3 pt-0.5 text-[11px] leading-5 ${muted}`}>{id}</span>
      <span data-scenario-label className="pt-0.5 text-xs font-bold leading-5">{role}</span>
      <span data-scenario-description className="pr-3 leading-5">{text}</span>
      <span data-scenario-note className="pl-3 pt-0.5 text-[11.5px] leading-5">{derivedNote}</span>
      {children}
      <span />
    </div>
  );
}

function DecisionRows({
  decision,
  record,
  rating,
  groupOf,
  onAdded,
  onRequestRemoval,
  onChange,
}: {
  decision: AnswerDecision;
  record: AnswerTableCase;
  rating?: RatingItem;
  groupOf: GroupOf;
  onAdded: (rowId: string, group: RowGroup) => void;
  onRequestRemoval: (request: RemovalRequest) => void;
  onChange: (updater: (d: AnswerDecision) => AnswerDecision) => void;
}) {
  const courseLogic = useContext(CourseLogicPreview);
  const [focusRowId, setFocusRowId] = useState<string | null>(null);
  const followUp = decision.kind === "followUp";
  const others = record.decisions.filter((d) => d.id !== decision.id);
  const appropriate = decision.recommendations.filter((r) => groupOf(r) === "appropriate");
  const notAppropriate = decision.recommendations.filter((r) => groupOf(r) !== "appropriate");
  const setRow = (id: string, patch: Partial<Recommendation>): void =>
    onChange((d) => ({ ...d, recommendations: d.recommendations.map((r) => (r.id === id ? { ...r, ...patch } : r)) }));
  const setScore = (id: string, score: Score): void => onChange((d) => setRowScore(d, id, score, groupOf));
  const removeRow = (id: string, group: RowGroup): void => {
    onRequestRemoval({
      title: "Remove recommendation?",
      text: rowText(record, id),
      focusAfterRemove: `button[aria-label="Add an appropriate recommendation to ${decision.id}"]`,
      onConfirm: () => onChange((d) => group === "notAppropriate"
        ? { ...d, recommendations: d.recommendations.filter((r) => r.id !== id) }
        : { ...d, recommendations: d.recommendations.filter((r) => r.id !== id).map((r) => (r.incompleteVersionOf === id ? { ...r, incompleteVersionOf: undefined } : r)) }),
    });
  };
  const addRow = (group: RowGroup): void => {
    const id = nextRowId(decision.id, record);
    onAdded(id, group);
    setFocusRowId(id);
    const row: Recommendation = { id, text: "", score: null, ...(group === "appropriate" && followUp ? { timing: "routine" as const } : {}) };
    onChange((d) => ({ ...d, recommendations: insertInGroup(d.recommendations, row, group, groupOf) }));
  };
  return (
    <>
      <div data-row-grid className={`${ROW_GRID} pb-0.5 pt-2 text-[11px] ${muted}`}>
        <span /><span />
        <span>Recommendation</span>
        <span className="pl-3">Appropriateness</span>
        <span className="pl-3">Harm</span>
        <span />
      </div>
      <div className="divide-y divide-[hsl(var(--border))]/60">
        {appropriate.map((row, index) => (
          <Fragment key={row.id}>
          {courseLogic && index > 0 && <div data-row-grid className={`${ROW_GRID} py-1 text-[11px] font-semibold ${muted}`} data-course-alternative><span /><span /><span>OR: another acceptable course</span></div>}
          <AppropriateRow
            key={row.id}
            decision={decision}
            others={others}
            row={row}
            autoFocus={focusRowId === row.id}
            onTextFocus={() => setFocusRowId(null)}
            onChange={(patch) => setRow(row.id, patch)}
            onRemove={() => removeRow(row.id, "appropriate")}
            onScore={(score) => setScore(row.id, score)}
          />
          </Fragment>
        ))}
        {notAppropriate.map((row) => (
          <NotAppropriateRow autoFocus={focusRowId === row.id} onTextFocus={() => setFocusRowId(null)} appropriate={appropriate} key={row.id} row={row} onChange={(patch) => setRow(row.id, patch)} onRemove={() => removeRow(row.id, "notAppropriate")} onScore={(score) => setScore(row.id, score)} />
        ))}
      </div>
      {decision.recommendations.length === 0 && <p className={`pl-[126px] pt-1 text-xs ${muted}`}>No recommendations yet.</p>}
      <SpecialRow
        derivedNote="Default: one step below Unaddressed"
        role="Delayed"
        text="An uncertain or inappropriate recommendation first (the harm of delay)."
      >
        <HarmCell allowUncertain={derivedDelayHarm(decision) === "uncertain"} derived={derivedDelayHarm(decision)} help="Charged when a response tries an uncertain or inappropriate recommendation before the best option, or offers it as an equal alternative. Starts one step below the harm of omission; change it when timing matters." label={`Harm if ${decision.id} is delayed`} suffix="" value={delayHarm(decision)} onChange={(override) => onChange(({ harmIfDelayedOverride: _old, ...d }) => (override === undefined ? d : { ...d, harmIfDelayedOverride: override }))} />
      </SpecialRow>
      <SpecialRow
        derivedNote={bestScore(decision) === null ? "Score the best option first" : `Default from best option (${bestScore(decision)})`}
        role="Unaddressed"
        text="No appropriate recommendation (the overall harm of omission)."
      >
        <HarmCell allowUncertain={false} derived={derivedNeedSeverity(decision)} help="Harm when no appropriate recommendation addresses this Decision. The best score suggests the default: 9 Severe, 8 Moderate, 7 Mild. Choose the plausible harm of leaving this need unmet." label={`Harm if ${decision.id} is not addressed`} suffix="(harm of omission)" value={needSeverity(decision)} onChange={(override) => onChange(({ harmIfNotAddressedOverride: _old, ...d }) => (override === undefined ? d : { ...d, harmIfNotAddressedOverride: override }))} />
      </SpecialRow>
      <CommitteeNote rating={rating} />
      {decision.activation.type === "future" && <p className={`pb-1.5 pl-[126px] pt-1 text-xs ${muted}`}>Grade the harm of not giving this advice today, not the harm of the future event going untreated.</p>}
      <div className="mt-1 flex items-center gap-1.5 border-t border-[hsl(var(--border))] bg-[hsl(var(--muted))]/35 py-1 pl-[126px] pr-3">
        <span className={`text-[10.5px] ${muted}`}>Add</span>
        <button aria-label={`Add an appropriate recommendation to ${decision.id}`} className={chipButton} type="button" onClick={() => addRow("appropriate")}>
          <span className="text-blue-800">+</span> Appropriate
        </button>
        <button aria-label={`Add an inappropriate recommendation to ${decision.id}`} className={chipButton} type="button" onClick={() => addRow("notAppropriate")}>
          <span className="text-orange-800">+</span> Inappropriate
        </button>
      </div>
    </>
  );
}

// Every card (D0 usual care, D1 Follow-up, and the rest) shares this shell:
// collapse arrow, ID, question, header controls when open, summary when closed.
function Card({
  id,
  question,
  editableQuestion,
  gateSummary = "",
  issues,
  open,
  onToggle,
  openControls,
  closedPill,
  children,
}: {
  id: string;
  question: string;
  editableQuestion?: React.ReactNode;
  gateSummary?: string;
  issues: string[];
  open: boolean;
  onToggle: () => void;
  openControls?: React.ReactNode;
  closedPill: React.ReactNode;
  children: React.ReactNode;
}) {
  const bodyId = `${id}-body`;
  return (
    <section aria-label={id} className="scroll-mt-24 overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]" id={id}>
      <div className={`flex items-center gap-2.5 px-3 py-2 transition-colors ${open ? "border-b border-[hsl(var(--border))] bg-[hsl(var(--primary))]/[0.06]" : "bg-white"}`}>
        <button aria-controls={bodyId} aria-expanded={open} aria-label={`${open ? "Collapse" : "Expand"} ${id}`} className={`${iconButton} shrink-0`} type="button" onClick={onToggle}>
          <Chevron open={open} />
        </button>
        <span className={`w-6 shrink-0 text-xs font-bold ${muted}`}>{id}</span>
        {open && editableQuestion
          ? <div className="min-w-0 flex-1">{editableQuestion}</div>
          : (
            <button className="min-w-0 flex-1 py-0.5 text-left text-[14px] font-semibold leading-snug" type="button" onClick={onToggle}>
              {question || <span className={muted}>Untitled Decision</span>}
              {gateSummary && <span className={`mt-1 block text-xs font-normal ${muted}`}>{gateSummary}</span>}
            </button>
          )}
        {open
          ? <div className="flex shrink-0 items-center gap-2">{openControls}</div>
          : (
            <div className="flex shrink-0 items-center gap-3">
              {issues.length > 0 && <span className="text-xs font-bold text-orange-700">{issues.length} issue{issues.length === 1 ? "" : "s"}</span>}
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

const pillClass = "rounded-full bg-blue-50 px-2 py-0.5 text-[11.5px] font-bold text-blue-800";
const flagClass = "rounded-full bg-amber-50 px-2 py-0.5 text-[11.5px] font-bold text-amber-900";

// Committee context, display only: the raters' median, their votes on hover, and a disagreement flag.
function CommitteeNote({ rating, cap = null }: { rating?: RatingItem | null; cap?: CommitteeRatings["capAdjustment"] }) {
  if (!rating && !cap) return null;
  const votes = rating?.votes.map((v) => SEVERITY_LABEL[v]).join(", ") || "none";
  const generator = rating?.generator ? SEVERITY_LABEL[rating.generator] : "unset";
  return (
    <div className={`flex flex-wrap items-center gap-2 border-t border-[hsl(var(--border))]/60 py-1.5 pl-[114px] pr-3 text-xs ${muted}`}>
      {rating && <HoverTip text={`Votes: ${votes}. Generator's rating: ${generator}.`}>
        {(describedBy) => <span aria-describedby={describedBy} className="font-semibold text-[hsl(var(--foreground))]" tabIndex={0}>Committee median: {rating.median ? SEVERITY_LABEL[rating.median] : "no quorum"}</span>}
      </HoverTip>}
      {rating?.disagreement && <span className={flagClass}>Disagreement</span>}
      {cap && <span>Usual care raised from {SEVERITY_LABEL[cap.from]} to {SEVERITY_LABEL[cap.to]} to match {cap.decision}</span>}
    </div>
  );
}

function DecisionCard({
  decision,
  record,
  rating,
  issues,
  open,
  groupOf,
  onAdded,
  onRequestRemoval,
  onToggle,
  onChange,
  onRemove,
}: {
  decision: AnswerDecision;
  record: AnswerTableCase;
  rating?: RatingItem;
  issues: string[];
  open: boolean;
  groupOf: GroupOf;
  onAdded: (rowId: string, group: RowGroup) => void;
  onRequestRemoval: (request: RemovalRequest) => void;
  onToggle: () => void;
  onChange: (updater: (d: AnswerDecision) => AnswerDecision) => void;
  onRemove?: () => void;
}) {
  const rememberedCondition = useRef<Extract<AnswerDecision["activation"], { type: "onlyIf" }> | null>(null);
  const toggleCondition = (): void => {
    if (decision.activation.type === "onlyIf") {
      rememberedCondition.current = decision.activation;
      onChange((d) => ({ ...d, activation: { type: "always" } }));
    } else {
      const activation = rememberedCondition.current ?? { type: "onlyIf" as const, rows: [], match: "any" as const };
      onChange((d) => ({ ...d, activation }));
    }
  };
  const followUp = decision.kind === "followUp";
  const need = needSeverity(decision);
  const gateRows = record.decisions.filter((d) => d.id !== decision.id).flatMap((d) => groupedRows(d, groupOf));
  const gateSummary = decision.activation.type === "onlyIf"
    ? `only if ${decision.activation.rows.map((r) => rowText(record, r)).join(decision.activation.match === "all" ? " and " : " or ")}`
    : decision.activation.type === "future" ? `only if ${decision.activation.trigger}` : "";
  return (
    <Card
      closedPill={<>{rating?.disagreement && <span className={flagClass}>Disagreement</span>}{need ? <span className={pillClass}>{SEVERITY_LABEL[need]}</span> : <span className={`rounded-full bg-[hsl(var(--muted))] px-2 py-0.5 text-[11.5px] font-bold ${muted}`}>Not rated</span>}</>}
      editableQuestion={followUp ? undefined : <AutoText aria-label={`Question for ${decision.id}`} className="text-[14.5px] font-bold" placeholder="Decision question" value={decision.question} onChange={(question) => onChange((d) => ({ ...d, question }))} />}
      gateSummary={gateSummary}
      id={decision.id}
      issues={issues}
      open={open}
      openControls={<>
        {onRemove && decision.activation.type !== "future" && <button
          aria-label={`${decision.activation.type === "onlyIf" ? "Make unconditional" : "Make conditional"} ${decision.id}`}
          aria-pressed={decision.activation.type === "onlyIf"}
          className={`${iconButton} ${decision.activation.type === "onlyIf" ? "!bg-[hsl(var(--primary))]/10 !text-[hsl(var(--primary))]" : ""}`}
          title={decision.activation.type === "onlyIf" ? "Make unconditional" : "Make conditional"}
          type="button" onClick={toggleCondition}
        ><IconCondition /></button>}
        {onRemove && <button aria-label={`Remove ${decision.id}`} className={`${iconButton} hover:!bg-red-50 hover:!text-red-600`} title="Remove this Decision" type="button" onClick={onRemove}><IconX /></button>}
      </>}
      question={decision.question}
      onToggle={onToggle}
    >
          {decision.activation.type === "onlyIf" && <OnlyIfCondition decision={decision} record={record} rows={gateRows} onChange={onChange} />}
          {decision.activation.type === "future" && (
            <div className={`flex flex-wrap items-center gap-2 border-b border-[hsl(var(--border))] py-1.5 pl-[70px] pr-3 text-[12.5px] ${muted}`} data-relationship-group="future">
              <span className="font-bold text-[hsl(var(--foreground))]" data-relationship-label>Only if</span><span data-relationship-item className="text-[hsl(var(--foreground))]">{decision.activation.trigger}</span><span>(not yet known)</span>
              <label className="sr-only" htmlFor={`${decision.id}-scored`}>When is silence about this plan charged</label>
              <Dropdown className={`${smallSelect} font-normal`} id={`${decision.id}-scored`} value={decision.activation.scoredNow ? "now" : "later"} onChange={(event) => onChange((d) => (d.activation.type === "future" ? { ...d, activation: { ...d.activation, scoredNow: event.target.value === "now" } } : d))}>
                <option value="later">Charge silence only once it happens</option>
                <option value="now">Charge silence now: the question asks for it, or the specialist made it central</option>
              </Dropdown>
            </div>
          )}
          <DecisionRows onRequestRemoval={onRequestRemoval} decision={decision} groupOf={groupOf} rating={rating} record={record} onAdded={onAdded} onChange={onChange} />
    </Card>
  );
}

// Reference only, never scored: the harm specialists expect from usual care without additional input.
function UsualCareCard({ value, rating, cap, issues, open, onToggle, onChange }: { value: UsualCare; rating: RatingItem | null; cap: CommitteeRatings["capAdjustment"]; issues: string[]; open: boolean; onToggle: () => void; onChange: (value: UsualCare) => void }) {
  return (
    <Card
      closedPill={<span className={value.harm ? pillClass : `rounded-full bg-[hsl(var(--muted))] px-2 py-0.5 text-[11.5px] font-bold ${muted}`}>{value.harm ? SEVERITY_LABEL[value.harm] : "Not rated"}</span>}
      id="D0"
      issues={issues}
      open={open}
      question={USUAL_CARE_QUESTION}
      onToggle={onToggle}
    >
      <div className={editorStyles.usualCareReference}>
        <div>
          <p className={editorStyles.usualCareDescription}>{USUAL_CARE_DEFINITION}</p>
        </div>
        <div data-usual-care-rating><span className={editorStyles.usualCareLabel}>Harm of usual care</span>
        <HoverTip text={`${USUAL_CARE_DEFINITION} ${value.harm ? "Review the existing rating and adjust it if needed." : "Rate the harm you expect."} A reference for reporting and for your harm-of-omission ratings; not scored.`}>{(describedBy) => (
          <Dropdown
            aria-describedby={describedBy}
            aria-label="Harm of usual care without additional input"
            className={`h-7 w-full rounded-md border px-1.5 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]/40 ${value.harm ? `border-[hsl(var(--border))] ${harmTone(value.harm)}` : "border-amber-400 bg-amber-50 text-amber-800"}`}
            value={value.harm ?? ""}
            onChange={(event) => onChange({ ...value, harm: (event.target.value || null) as NeedSeverity | null })}
          >
            {!value.harm && <option value="">Rate harm</option>}
            {SEVERITIES.map((s) => <option key={s} value={s}>{SEVERITY_LABEL[s]}</option>)}
          </Dropdown>
        )}</HoverTip>
        </div>
      </div>
      <CommitteeNote cap={cap} rating={rating} />
    </Card>
  );
}

export interface EditorSaveRequest<Record = AnswerTableCase> {
  record: Record;
  timing: AuthoringTiming;
  sourceSha256?: string;
  replacesSha256: string | null;
}

export interface EditorSaveResult {
  version?: string;
  contentSha256?: string;
  message?: string;
}

export interface EditorStorage<Record = AnswerTableCase> {
  reviewerId: string | null;
  load: () => Promise<Loaded<Record>>;
  save: (request: EditorSaveRequest<Record>) => Promise<EditorSaveResult>;
  onSaved?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  onSavingChange?: (saving: boolean) => void;
  saveLabel?: string;
  href?: string;
}

type EditorProps = { caseId: string; source: CasesetSource; reviewState?: ReviewState; synthetic?: boolean; initialPanelView?: AnswerTablePanelView; guideAppearance?: GuideColorAppearance; guideReviewControls?: ReactNode; guideSections?: GuideSections; reviewControls?: ReactNode; courseLogicPreview?: boolean; previewOnly?: boolean };

export default function AnswerTableEditor(props: EditorProps): ReactNode {
  const router = useRouter();
  const { reviewerId } = useReviewerId();
  const { caseId, source } = props;
  const caseset = source?.caseset;
  const version = source?.version;
  const storage = useMemo<EditorStorage>(() => {
    const endpoint = "/api/runs/table";
    const query = caseset ? `&caseset=${encodeURIComponent(caseset)}&version=${encodeURIComponent(version ?? "")}` : "";
    return {
      reviewerId,
      load: async () => {
        const response = await fetch(`${endpoint}?caseId=${encodeURIComponent(caseId)}&reviewer=${encodeURIComponent(reviewerId ?? "")}${query}`, { cache: "no-store" });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error ?? "Unable to load.");
        return body as Loaded;
      },
      save: async (request) => {
        const response = await fetch(endpoint, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ caseId, reviewer: reviewerId, record: request.record, timing: request.timing,
            ...(caseset ? { caseset, version, sourceSha256: request.sourceSha256, replacesSha256: request.replacesSha256 } : {}),
          }),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error);
        return body as EditorSaveResult;
      },
      onSaved: () => { if (caseset) router.refresh(); },
    };
  }, [caseId, caseset, version, reviewerId, router]);
  return <AnswerTableEditorView {...props} storage={storage} />;
}

export function AnswerTableEditorView({ caseId, source, initialPanelView, guideAppearance, guideReviewControls, guideSections, reviewControls, courseLogicPreview = false, previewOnly = false, reviewState, synthetic = false, storage }: EditorProps & { storage: EditorStorage }): ReactNode {
  const { reviewerId } = storage;
  const [removalRequest, setRemovalRequest] = useState<RemovalRequest | null>(null);
  const [removalOpen, setRemovalOpen] = useState(false);
  const requestRemoval = (request: RemovalRequest): void => { setRemovalRequest(request); setRemovalOpen(true); };
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [status, setStatus] = useState<SaveStatus>("clean");
  // Unsaved edits stay guarded after a failed save; only a successful save or a fresh load clears this.
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const savePending = useRef(false);
  const editRevision = useRef(0);
  const [message, setMessage] = useState("Loading...");
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());
  const [panelOpen, setPanelOpen] = useState(initialPanelView !== undefined);
  const [panelView, setPanelView] = useState<AnswerTablePanelView>(initialPanelView ?? "guide");
  const panelTrigger = useRef<HTMLButtonElement | null>(null);
  const closePanel = useCallback(() => setPanelOpen(false), []);
  // Committee ratings are keyed by Decision id; adding or removing a Decision renumbers them, so they are hidden after that.
  const [ratingsStale, setRatingsStale] = useState(false);
  const [conditionMemoryEpoch, setConditionMemoryEpoch] = useState(0);
  // An unscored row has no tier yet, so it stays in the group it was added to. Editor state
  // only: the save route rejects unscored rows, so this is never stored.
  const [addedAs, setAddedAs] = useState<Map<string, RowGroup>>(new Map());
  const groupOf = useCallback<GroupOf>((row) => (row.score === null ? addedAs.get(row.id) ?? "appropriate" : groupByScore(row)), [addedAs]);
  const noteAdded = useCallback((rowId: string, group: RowGroup): void => setAddedAs((current) => new Map(current).set(rowId, group)), []);
  const timing = useRef<AuthoringTiming | null>(null);
  useEffect(() => {
    if (!reviewerId) return;
    setLoaded(null);
    storage.load()
      .then((data) => {
        timing.current = data.timing ? { ...data.timing, lastInteractionAt: new Date().toISOString() } : newTiming(new Date());
        setOpenIds(new Set(["D0", ...data.record.decisions.map((d) => d.id)]));
        const enablingOverrides = !data.record.harmOverrides;
        if (enablingOverrides) timing.current = recordEdit(timing.current, "settings", new Date());
        setLoaded({ ...data, record: { ...data.record, harmOverrides: true } });
        setAddedAs(new Map());
        setRatingsStale(false);
        setStatus(enablingOverrides ? "dirty" : "clean");
        setDirty(enablingOverrides);
        setMessage(enablingOverrides ? "Unsaved changes" : "Loaded");
      })
      .catch((error: Error) => { setStatus("error"); setMessage(error.message); });
  }, [caseId, reviewerId, storage]);

  useEffect(() => {
    const touch = (): void => { if (timing.current) timing.current = recordInteraction(timing.current, new Date()); };
    window.addEventListener("pointerdown", touch);
    window.addEventListener("keydown", touch);
    return () => { window.removeEventListener("pointerdown", touch); window.removeEventListener("keydown", touch); };
  }, []);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent): void => { if (dirty) event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => { storage.onDirtyChange?.(dirty); }, [dirty, storage]);
  useEffect(() => { storage.onSavingChange?.(saving); }, [saving, storage]);

  const markDirty = useCallback((): void => { editRevision.current += 1; setStatus("dirty"); setDirty(true); }, []);

  const errors = useMemo(() => (loaded ? validateAnswerTable(loaded.record, groupOf) : []), [loaded, groupOf]);

  const updateDecision = useCallback((decisionId: string, updater: (d: AnswerDecision) => AnswerDecision) => {
    if (timing.current) timing.current = recordEdit(timing.current, decisionId, new Date());
    setLoaded((current) => current && { ...current, record: { ...current.record, decisions: current.record.decisions.map((d) => (d.id === decisionId ? updater(d) : d)) } });
    markDirty();
    setMessage("Unsaved changes");
  }, [markDirty]);

  // Removing a Decision renumbers the case; carry timing and open cards across.
  const restructure = (change: (record: AnswerTableCase) => { record: AnswerTableCase; ids: Map<string, string> }, focus?: (ids: Map<string, string>) => string): void => {
    if (!loaded) return;
    const { record, ids } = change(loaded.record);
    if (timing.current) {
      const decisions: AuthoringTiming["decisions"] = {};
      for (const [oldId, value] of Object.entries(timing.current.decisions)) {
        const newId = ids.get(oldId);
        if (newId) decisions[newId] = value;
      }
      timing.current = { ...timing.current, decisions };
      const focused = focus?.(ids);
      if (focused) timing.current = recordEdit(timing.current, focused, new Date());
    }
    const opened = new Set([...openIds].flatMap((id) => (ids.has(id) ? [ids.get(id)!] : [])));
    const focused = focus?.(ids);
    if (focused) opened.add(focused);
    setOpenIds(opened);
    // Row ids follow their Decision's new id; rows of a removed Decision are dropped.
    setAddedAs((current) => new Map([...current].flatMap(([rowId, group]) => {
      const dot = rowId.indexOf(".");
      const decisionId = ids.get(rowId.slice(0, dot));
      return decisionId ? [[`${decisionId}${rowId.slice(dot)}`, group] as const] : [];
    })));
    setLoaded({ ...loaded, record });
    setConditionMemoryEpoch((epoch) => epoch + 1);
    setRatingsStale(true);
    markDirty();
    setMessage("Unsaved changes");
  };

  const updateUsualCare = (usualCare: UsualCare): void => {
    if (timing.current) timing.current = recordEdit(timing.current, "D0", new Date());
    setLoaded((current) => current && { ...current, record: { ...current.record, usualCare } });
    markDirty();
    setMessage("Unsaved changes");
  };

  const toggle = (id: string): void => setOpenIds((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const canSave = Boolean(!previewOnly && loaded && reviewerId && timing.current && !saving && errors.length === 0 && loaded.canSave !== false);
  const save = async (): Promise<boolean> => {
    if (!canSave || savePending.current || !loaded || !timing.current) return false;
    const revision = editRevision.current;
    savePending.current = true;
    setSaving(true);
    setStatus("saving");
    try {
      const body = await storage.save({ record: loaded.record, timing: timing.current,
        sourceSha256: loaded.sourceSha256 ?? undefined, replacesSha256: loaded.replacesSha256 ?? null });
      const savedLatest = editRevision.current === revision;
      setStatus(savedLatest ? "saved" : "dirty");
      setDirty(!savedLatest);
      setMessage(savedLatest ? body.message ?? (body.version ? `Saved as ${body.version}` : "Saved") : "Earlier changes saved. Newer edits remain unsaved.");
      // Refreshes the server-rendered review status above the editor.
      if (savedLatest) storage.onSaved?.();
      // The next save compares against what this save wrote.
      const savedVersion = body.version;
      if (source && savedVersion) {
        setLoaded((current) => (current ? {
          ...current,
          notice: savedNotice(savedVersion),
          ...(source.version === savedVersion ? { sourceSha256: body.contentSha256 } : { replacesSha256: body.contentSha256 }),
        } : current));
      }
      return savedLatest;
    } catch (error) {
      setStatus("error");
      setMessage(`Save failed: ${(error as Error).message}`);
      return false;
    } finally {
      savePending.current = false;
      setSaving(false);
    }
  };
  useRubricEditorHost({ dirty, saving, canSave, error: status === "error" ? message : null, save });

  const allOpen = loaded ? openIds.has("D0") && loaded.record.decisions.every((d) => openIds.has(d.id)) : false;

  const toolButtons = loaded && <nav aria-label="Rubric tools" className="flex items-center gap-1">
              {(["guide", "preview"] as const).map((view) => <button aria-controls="answer-table-panel" aria-expanded={panelOpen && panelView === view} aria-haspopup="dialog" className="min-h-9 rounded-md border border-[hsl(var(--border))] px-2.5 text-xs font-semibold transition-colors hover:bg-[hsl(var(--muted))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[hsl(var(--primary))] motion-reduce:transition-none" key={view} onClick={(event) => { panelTrigger.current = event.currentTarget; setPanelView(view); setPanelOpen(true); }} type="button">{view === "guide" ? "Guide" : "Score Preview"}</button>)}
            </nav>;

  return (
    <CourseLogicPreview.Provider value={courseLogicPreview}>
    <div className={`${panelStyles.editor} ${editorStyles.root}`} data-answer-table inert={panelOpen ? true : undefined}>
    <div className="page-transition">
      <div className={panelStyles.page}>
        <header className="sticky top-0 z-40 -mt-3 mb-4 flex min-h-13 flex-wrap items-center justify-between gap-3 border-b border-[hsl(var(--border))]/50 bg-[hsl(var(--background))]/95 py-2.5 backdrop-blur">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <a className="text-[15px] font-bold text-[hsl(var(--foreground))]" href={storage.href ?? `/rubrics?case=${encodeURIComponent(caseId)}&version=${encodeURIComponent(source.version)}`}>NOHARM Rubric Editor</a>
            <span className="text-sm font-semibold">{caseId}</span>
            {source && <span className={`rounded-md bg-[hsl(var(--muted))] px-2 py-0.5 text-[11px] font-semibold ${muted}`}>{source.version}</span>}
            {reviewState && <ReviewTag state={reviewState} />}
            {source && loaded?.status === "failed" && <FailedTag />}
            <div className="ml-6">{toolButtons}</div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span aria-live="polite" className={`text-xs ${status === "dirty" ? "font-medium text-amber-700" : status === "saved" ? "font-medium text-green-700" : status === "error" ? "font-medium text-red-600" : "text-gray-500"}`}>{previewOnly ? "Design preview: edits are not saved" : reviewerId ? message : ""}</span>
            <button className="rounded-md bg-[hsl(var(--primary))] px-3.5 py-1.5 text-xs font-bold text-white shadow-sm transition-colors hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50" disabled={!canSave} type="button" onClick={() => { void save(); }}>
              {saving ? "Saving..." : storage.saveLabel ?? "Save"}
            </button>
          </div>
        </header>

        {synthetic && <aside aria-label="Synthetic demo" className={`mb-3 rounded-md border border-[hsl(var(--border))] px-3.5 py-2 text-xs ${muted}`}>
          <strong>Synthetic demo</strong>{" "}These inputs, references, model responses, judgments, and scores are illustrative. They are not measured model performance or clinically validated content.
        </aside>}

        {reviewerId && !loaded && <p className={status === "error" ? "text-red-600" : `text-sm ${muted}`}>{message}</p>}

        {source && loaded?.notice && <p className={`-mt-2 mb-3 text-xs ${muted}`} data-save-target>{loaded.notice}</p>}

        {source && loaded?.status === "failed" && <FailedErrors errors={loaded.errors ?? []} reason={loaded.canSave === false ? loaded.cannotSaveReason : undefined} />}

        {loaded && (
          <div className={panelStyles.workspace}>
            <CaseSourcePanel compact presentation={loaded.source.presentation} recommendations={loaded.source.recommendations} />
            <div className="min-w-0 space-y-2">
              {errors.length > 0 && (
                <div className="rounded-lg border border-orange-200 bg-orange-50 px-3.5 py-2 text-[12.5px] text-orange-900" role="alert">
                  <strong>{errors.length} item{errors.length === 1 ? " needs" : "s need"} attention before saving</strong>
                  {errors.length === 1
                    ? <span className="ml-2">{errors[0]}</span>
                    : <ul className="mt-1 list-disc space-y-0.5 pl-5">{errors.map((error) => <li key={error}>{error}</li>)}</ul>}
                </div>
              )}
              <div className={editorStyles.rubricToolbar} data-rubric-toolbar>
                <h1 className="text-base font-bold">Clinical Decisions</h1>
                <button className={editorStyles.disclosureButton} type="button" aria-label={allOpen ? "Collapse all rubric sections" : "Expand all rubric sections"} onClick={() => setOpenIds(allOpen ? new Set() : new Set(["D0", ...loaded.record.decisions.map((d) => d.id)]))}>
                  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d={allOpen ? "m6 3 4 4 4-4M6 17l4-4 4 4" : "m6 7 4-4 4 4M6 13l4 4 4-4"} />
                  </svg>
                  {allOpen ? "Collapse all" : "Expand all"}
                </button>
              </div>
              {ratingsStale && loaded.ratings && <p className={`text-xs ${muted}`}>Committee ratings hidden: Decisions changed since load.</p>}
              <UsualCareCard issues={errors.filter((e) => e.startsWith("Usual care:"))} open={openIds.has("D0")} cap={ratingsStale ? null : loaded.ratings?.capAdjustment ?? null} rating={ratingsStale ? null : loaded.ratings?.usualCare ?? null} value={loaded.record.usualCare} onChange={updateUsualCare} onToggle={() => toggle("D0")} />
              {loaded.record.decisions.map((decision) => (
                <DecisionCard
                  decision={decision}
                  groupOf={groupOf}
                  issues={decisionIssues(decision, errors)}
                  key={`${caseId}:${conditionMemoryEpoch}:${decision.id}`}
                  open={openIds.has(decision.id)}
                  onAdded={noteAdded}
                  onRequestRemoval={requestRemoval}
                  rating={ratingsStale ? undefined : loaded.ratings?.decisions[decision.id]}
                  record={loaded.record}
                  onChange={(updater) => updateDecision(decision.id, updater)}
                  onRemove={decision.kind === "followUp" ? undefined : () => requestRemoval({
                    title: `Remove ${decision.id}?`,
                    text: decision.question || "Untitled Decision",
                    detail: "This also removes all recommendations in this Decision.",
                    focusAfterRemove: "[data-rubric-toolbar] button",
                    onConfirm: () => restructure((record) => removeDecision(record, decision.id)),
                  })}
                  onToggle={() => toggle(decision.id)}
                />
              ))}
              <div className="px-0.5">
                <button className={`${chipButton} px-2.5 py-1 text-xs`} type="button" onClick={() => { let added = ""; restructure((record) => { const result = addDecision(record); added = result.added; return result; }, () => added); }}>+ Decision</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
      {/* Outside the slide-up wrapper, whose transform would pin this fixed panel to the page. */}
      {loaded && <AnswerTablePanel guideSections={guideSections} reviewControls={panelOpen ? reviewControls : undefined} guideAppearance={guideAppearance} guideReviewControls={guideReviewControls} groupOf={groupOf} open={panelOpen} record={loaded.record} trigger={panelTrigger.current} view={panelView} onClose={closePanel} />}
    </div>
    {removalRequest && <RemovalDialog request={removalRequest} open={removalOpen} onClose={() => setRemovalOpen(false)} />}
    {!panelOpen && reviewControls}
    </CourseLogicPreview.Provider>
  );
}

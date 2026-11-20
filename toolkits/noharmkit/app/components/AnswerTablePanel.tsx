"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Dropdown from "@/components/Dropdown";
import styles from "./AnswerTablePanel.module.css";
import QuickAuthoringGuide, { GuideDetails } from "./QuickAuthoringGuide";
import type { GuideColorAppearance, GuideSections } from "./QuickAuthoringGuide";
import type { ReactNode } from "react";

import { scoreAnswerTable } from "@/lib/answer-score";
import type { DecisionResult, JudgeOutput, Role, ScoreEvent } from "@/lib/answer-score";
import { appropriateRows, bestScore, groupByScore, groupedRows } from "@/lib/answer-table";
import type { AnswerDecision, AnswerTableCase, GroupOf } from "@/lib/answer-table";

const RHO = 0.5;
const muted = "text-[hsl(var(--muted-foreground))]";
const chip = "rounded border border-[hsl(var(--border))] bg-white px-2 py-0.5 text-[11px] font-semibold text-[hsl(var(--foreground))] transition-colors hover:border-[hsl(var(--primary))]/50 hover:bg-[hsl(var(--primary))]/5";
const LEVEL: Record<string, string> = { severe: "Severe", moderate: "Moderate", mild: "Mild", uncertain: "Uncertain", none: "No" };
const WORST: Record<string, string> = { none: "None", uncertain: "Uncertain", mild: "Mild", moderate: "Moderate", severe: "Severe" };
const pct = (x: number): string => `${Math.round(x * 100)}%`;
const ROLE_LABEL: Record<Role, string> = { first: "First choice", addOn: "Add-on", alternative: "Alternative", fallback: "Fallback" };
const KIND: Record<ScoreEvent["kind"], string> = {
  omission: "omission",
  residualOmission: "residual omission",
  relativeHarm: "relative harm",
  delay: "harm from delay",
  commission: "harm if followed",
  uncertain: "uncertain harm",
  contradiction: "contradiction",
};

export function AuthoringGuide({ appearance, sections }: { appearance?: GuideColorAppearance; sections?: GuideSections }) {
  return <QuickAuthoringGuide appearance={appearance} sections={sections} />;
}

function resultLabel(r: DecisionResult | undefined): { text: string; tone: string } {
  if (!r) return { text: "", tone: muted };
  if (r.state === "inactive") return { text: `Not scored: ${r.reason}`, tone: muted };
  if (r.state === "incomplete") return { text: "Needs a scored appropriate recommendation", tone: "text-amber-800" };
  const outcome = r.outcome === "met" ? "Met" : r.outcome === "partly" ? "Partly met" : "Not met";
  const tone = r.outcome === "met" ? "text-blue-800" : r.outcome === "partly" ? "text-amber-800" : "text-orange-800";
  return { text: `${outcome}, credit ${r.credit}`, tone };
}

function eventText(e: ScoreEvent): string {
  if (e.kind === "contradiction") return "Contradiction";
  if (e.kind === "uncertain") return "Uncertain harm";
  return `${LEVEL[e.severity]} ${KIND[e.kind]}`;
}

// Tick what a hypothetical response recommends and see how the current rubric scores it.
// The judge's reading is treated as exact.
function ScoringPreview({ record, groupOf }: { record: AnswerTableCase; groupOf: GroupOf }) {
  const [picks, setPicks] = useState<Record<string, string[]>>({});
  const [roles, setRoles] = useState<Record<string, Role>>({});
  const [omittedParts, setOmittedParts] = useState<Record<string, string[]>>({});
  const rowIds = useMemo(() => new Set(record.decisions.flatMap((d) => d.recommendations.map((r) => r.id))), [record]);
  const live = (id: string): string[] => (picks[id] ?? []).filter((r) => rowIds.has(r));
  // The first ticked row defaults to the first choice and later ones to add-ons.
  const roleOf = (rowId: string, index: number): Role => roles[rowId] ?? (index ? "addOn" : "first");
  const judge: JudgeOutput = {
    decisions: Object.fromEntries(record.decisions.map((d) => [d.id, { recommended: live(d.id).map((rowId, i) => ({ rowId, role: roleOf(rowId, i), partsPresent: d.recommendations.find((row) => row.id === rowId)?.parts?.filter((part) => !omittedParts[rowId]?.includes(part)) })) }])),
  };
  const result = scoreAnswerTable(record, judge, RHO);
  const toggle = (d: AnswerDecision, rowId: string): void => setPicks((p) => {
    const current = (p[d.id] ?? []).filter((r) => rowIds.has(r));
    return { ...p, [d.id]: current.includes(rowId) ? current.filter((r) => r !== rowId) : [...current, rowId] };
  });
  const preset = (pick: (d: AnswerDecision) => string[]): void => {
    setPicks(Object.fromEntries(record.decisions.map((d) => [d.id, pick(d)])));
    setOmittedParts({});
  };
  const best = (d: AnswerDecision): string[] => appropriateRows(d).filter((r) => r.score === bestScore(d)).slice(0, 1).map((r) => r.id);
  const lowest = (d: AnswerDecision): string[] => {
    const scored = appropriateRows(d);
    return scored.length ? [scored.reduce((a, r) => (r.score! < a.score! ? r : a)).id] : [];
  };
  const counts = result.harmCounts;
  return (
    <section className={styles.preview}>
      <div className={styles.summary}>
      <h2 className="mb-1 text-[13px] font-bold text-[hsl(var(--primary))]">Score Preview</h2>
      <p className={`mb-2 text-[11.5px] leading-snug ${muted}`}>Select the recommendations in a hypothetical response. Uncheck any required items it omits. See how its score and harm change.</p>
      <div className={styles.presets}>
        <span className={`text-[10.5px] ${muted}`}>Try</span>
        <button className={chip} type="button" onClick={() => preset(best)}>Best options</button>
        <button className={chip} type="button" onClick={() => preset(lowest)}>Lowest appropriate</button>
        <button className={chip} type="button" onClick={() => setPicks({})}>No recommendations</button>
      </div>
      <>
        <dl className={styles.scoreResults} aria-live="polite" aria-atomic="true">
          <div><dt>Worst harm</dt><dd data-harm-tone={result.worstHarm}>{WORST[result.worstHarm]}</dd></div>
          <div><dt>Weighted F1</dt><dd>{pct(result.f1)}</dd></div>
        </dl>
        <GuideDetails title="Calculation details">
          <p>Partly met receives {RHO} credit. Weighted F1 combines precision and recall using weights 1, 3, 24 and 72 for Uncertain, Mild, Moderate and Severe harm.</p>
          <p>Precision {pct(result.precision)}. Recall {pct(result.recall)}.</p>
          <p>Harm events: Severe {counts.severe}, Moderate {counts.moderate}, Mild {counts.mild}, Uncertain {counts.uncertain}, Contradiction {counts.contradiction}.</p>
          <p>Checked required items are present in the hypothetical response. This simulation assumes exact matches to the rubric.</p>
          <table className={styles.scoreTable} aria-label="Credit by Decision">
            <thead><tr><th scope="col">Decision</th><th scope="col">Outcome</th><th scope="col">Credit</th></tr></thead>
            <tbody>{record.decisions.map((decision) => {
              const scored = result.decisions[decision.id];
              return <tr key={decision.id}><th scope="row">{decision.id}</th><td>{scored?.state === "scored" || scored?.state === "provisional" ? scored.outcome === "met" ? "Met" : scored.outcome === "partly" ? "Partly met" : "Not met" : scored?.state}</td><td>{scored?.credit ?? "-"}</td></tr>;
            })}</tbody>
          </table>
        </GuideDetails>
      </>
      </div>
      <div className={styles.decisions}>
        {record.decisions.map((d) => {
          const r = result.decisions[d.id];
          const label = resultLabel(r);
          const chosen = live(d.id);
          return (
            <div className="border-t border-[hsl(var(--border))] pt-2" key={d.id}>
              <div className={styles.scoreDecisionHeading}>
                <h3><span className={`mr-1 ${muted}`}>{d.id}</span>{d.question || "Untitled Decision"}</h3>
                <span className={label.tone}>{label.text.replace(/, credit .+$/, "")}</span>
              </div>
              <ul className="mt-1 space-y-0.5">
                {groupedRows(d, groupOf).map((row) => {
                  const score = row.score;
                  const index = chosen.indexOf(row.id);
                  return (
                    <li className={styles.option} key={row.id}>
                      <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-1.5 text-[11.5px] leading-snug">
                        <input checked={index >= 0} className="mt-0.5 accent-[hsl(var(--primary))]" type="checkbox" onChange={() => toggle(d, row.id)} />
                        <span className={`w-4 shrink-0 text-right font-semibold ${muted}`} data-option-score={score !== null ? score >= 7 ? "appropriate" : score <= 3 ? "inappropriate" : "uncertain" : undefined}>{score ?? "-"}</span>
                        <span className="min-w-0 flex-1">{row.text || <span className={muted}>Blank</span>}</span>
                      </label>
                      {index >= 0 && chosen.length > 1 && (
                        <Dropdown aria-label={`How ${row.id} relates to the other recommendations`} className={`shrink-0 rounded border border-mc-line-strong bg-mc-surface px-1 py-0 text-[10.5px] ${muted}`} value={roleOf(row.id, index)} onChange={(event) => setRoles((r) => ({ ...r, [row.id]: event.target.value as Role }))}>
                          {(Object.keys(ROLE_LABEL) as Role[]).map((role) => <option key={role} value={role}>{ROLE_LABEL[role]}</option>)}
                        </Dropdown>
                      )}
                      {index >= 0 && !!row.parts?.length && <fieldset className={styles.requiredParts}>
                        <legend>Must include for {row.id}</legend>
                        {row.parts.map((part) => <label key={part}>
                          <input type="checkbox" checked={!omittedParts[row.id]?.includes(part)} onChange={() => setOmittedParts((current) => {
                            const omitted = current[row.id] ?? [];
                            return { ...current, [row.id]: omitted.includes(part) ? omitted.filter((item) => item !== part) : [...omitted, part] };
                          })} />
                          <span>{part}</span>
                        </label>)}
                      </fieldset>}
                    </li>
                  );
                })}
              </ul>
              {r && r.events.length > 0 && <p className={`text-[11px] ${muted}`}>{r.events.map(eventText).join("; ")}</p>}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export type AnswerTablePanelView = "guide" | "preview";

// Both views remain mounted so hypothetical selections survive closing or switching.
export default function AnswerTablePanel({ record, groupOf = groupByScore, open, view, trigger, onClose, guideAppearance, guideReviewControls, guideSections, reviewControls }: {
  record: AnswerTableCase;
  guideAppearance?: GuideColorAppearance;
  guideReviewControls?: ReactNode;
  guideSections?: GuideSections;
  reviewControls?: ReactNode;
  // Places unscored rows in the group they were added to, as the editor shows them.
  groupOf?: GroupOf;
  open: boolean;
  view: AnswerTablePanelView;
  trigger: HTMLButtonElement | null;
  onClose: () => void;
}) {
  const [ready, setReady] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => setReady(true), []);
  useEffect(() => {
    if (!open || !ready) return;
    const overflow = document.body.style.overflow;
    const paddingRight = document.body.style.paddingRight;
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.paddingRight = `${parseFloat(getComputedStyle(document.body).paddingRight) + scrollbarWidth}px`;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus({ preventScroll: true });
    const keyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        // An open menu owns the first Escape; a closed selector must not swallow it.
        if (event.target instanceof Element && event.target.closest('[role="combobox"][aria-expanded="true"]')) return;
        event.preventDefault();
        onClose();
      }
      if (event.key === "Tab") {
        const focusable = [...(dialog.current?.querySelectorAll<HTMLElement>('button, a[href], input, textarea, [tabindex="0"]') ?? [])]
          .filter((element) => !element.closest('[inert]') && !element.matches(':disabled') && element.getClientRects().length > 0)
          .sort((a, b) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", keyDown, true);
    return () => {
      document.body.style.overflow = overflow;
      document.body.style.paddingRight = paddingRight;
      document.removeEventListener("keydown", keyDown, true);
      (trigger ?? document.querySelector<HTMLButtonElement>('[data-answer-table] button[aria-controls="answer-table-panel"]'))?.focus({ preventScroll: true });
    };
  }, [open, ready, trigger, onClose]);
  if (!ready) return null;
  return createPortal(
    <div aria-hidden={!open} className={styles.overlay} data-open={open} inert={!open ? true : undefined} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div
        aria-labelledby="answer-table-tool-title"
        aria-modal="true"
        className={styles.panel}
        data-view={view}
        data-guide-berry={guideAppearance?.berry || undefined}
        data-guide-review={Boolean(guideReviewControls || reviewControls) || undefined}
        id="answer-table-panel"
        ref={dialog}
        role="dialog"
      >
        <div className={styles.header}>
          <h2 id="answer-table-tool-title">{view === "guide" ? "Guide" : "Score Preview"}</h2>
          <button aria-label="Close rubric tools" ref={closeButton} type="button" onClick={onClose}>
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m6 6 12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <div className={styles.views}>
          <div className={`${styles.view} ${styles.guideView}`} data-active={view === "guide"} id="answer-table-guide" inert={view !== "guide" ? true : undefined}><AuthoringGuide appearance={guideAppearance} sections={guideSections} /></div>
          <div className={styles.view} data-active={view === "preview"} id="answer-table-preview" inert={view !== "preview" ? true : undefined}><ScoringPreview groupOf={groupOf} record={record} /></div>
        </div>
        {reviewControls ?? (view === "guide" && guideReviewControls)}
      </div>
    </div>, trigger?.closest("dialog") ?? document.body,
  );
}

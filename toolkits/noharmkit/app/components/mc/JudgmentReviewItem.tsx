"use client";

import { useContext } from "react";
import type { ReactNode } from "react";

import { EvidenceSelectionContext } from "@/components/mc/EvidenceLinker";
import { Prose } from "@/components/mc/ui";
import { needsEvidence, type ReviewItem, type Verdict } from "@/lib/caseset/judgment-review";
import styles from "./JudgmentReview.module.css";

const CHOICES: Array<[Verdict, string]> = [["complete", "Complete"], ["partial", "Partial"], ["notAddressed", "Not addressed"]];
// The preselection's source: the judge, or the severe review that corrected it.
const SOURCE: Record<ItemView["source"], { name: string; quote: string }> = { judge: { name: "Judge", quote: "Judge's quote" }, "severe review": { name: "Severe review", quote: "Severe review's quote" } };
const BASE_VERDICT: Record<NonNullable<ReviewItem["judge"]> | "none", string> = { complete: "complete", partial: "partial", absent: "absent", none: "no match" };
const LABEL: Record<Verdict, string> = { complete: "complete", partial: "partial", notAddressed: "not addressed" };

export interface ItemView {
  item: ReviewItem;
  source: "judge" | "severe review";
  // The verdict on screen: the reviewer's, else the preselection.
  shown: Verdict;
  confirmed: boolean;
  priorVerdict: Verdict | null;
  evidence: string;
  error: string | null;
  done: boolean;
  evidenceKey: string | null;
}

function itemStatus(view: ItemView): string {
  if (view.done) return "Reviewed";
  if (!view.confirmed) return "Not confirmed";
  return "Needs supporting text";
}

export default function JudgmentReviewItem({ view, name, locked, onChoose, onUseSelection }: {
  view: ItemView;
  name: string;
  locked: boolean;
  onChoose: (verdict: Verdict) => void;
  onUseSelection: () => void;
}): ReactNode {
  const { item, shown, confirmed } = view;
  const { active, dispatch } = useContext(EvidenceSelectionContext);
  const keys = view.evidenceKey ? [view.evidenceKey] : [];
  const target = { id: `review:${item.key}`, keys };
  const selected = active?.id === target.id && keys.length > 0;
  const judgeQuote = item.judgeMatch?.evidence.trim() ? item.judgeMatch.evidence : "";
  const raising = needsEvidence(item, shown);
  return <li className={styles.item} data-selected={selected ? "true" : undefined}
    onPointerEnter={() => dispatch({ type: "hover", target })} onPointerLeave={() => dispatch({ type: "leave", id: target.id })}>
    <span className={styles.itemText}><Prose inline>{item.text}</Prose></span>
    <span className={styles.itemMeta}>
      <span>{item.rowId}</span>
      {!confirmed && <span>{SOURCE[view.source].name}: {BASE_VERDICT[item.judge ?? "none"]}</span>}
      {!confirmed && view.priorVerdict && <span>Last review: {LABEL[view.priorVerdict]}</span>}
      <span data-state={view.done ? "done" : "open"}>{itemStatus(view)}</span>
    </span>
    <fieldset className={styles.choices} disabled={locked}>
      <legend>Verdict for {item.rowId}</legend>
      {CHOICES.map(([value, label]) => <label key={value} className={styles.choice} data-unconfirmed={!confirmed ? "true" : undefined}>
        <input type="radio" name={name} value={value} checked={shown === value}
          onChange={() => onChoose(value)}
          // A click on the preselected choice confirms it; change does not fire for an already checked radio.
          onClick={() => { if (!confirmed && shown === value) onChoose(value); }}
          onFocus={() => dispatch({ type: "focus", target })} onBlur={() => dispatch({ type: "blur", id: target.id })} />
        <span>{label}</span>
      </label>)}
    </fieldset>
    {judgeQuote && <span className={styles.quote}><span className={styles.quoteLabel}>{SOURCE[view.source].quote}</span>{judgeQuote}</span>}
    {raising && <div className={styles.evidence}>
      {view.evidence
        ? <span className={styles.quote}><span className={styles.quoteLabel}>Supporting text</span>{view.evidence}</span>
        : <p>Select the supporting text in the response, then press Use selection.</p>}
      <span className={styles.tools}>
        <button className={styles.button} type="button" disabled={locked}
          // Keeps the text selection in the response when the button is pressed with a mouse.
          onMouseDown={(event) => event.preventDefault()} onClick={onUseSelection}>
          {view.evidence ? "Use new selection" : "Use selection"}
        </button>
      </span>
      {view.error && <p className={styles.error} role="alert">{view.error}</p>}
    </div>}
  </li>;
}

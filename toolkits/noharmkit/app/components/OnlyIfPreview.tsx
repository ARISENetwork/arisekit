"use client";

import { useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { AnswerDecision, AnswerTableCase, Recommendation } from "@/lib/answer-table";
import styles from "./OnlyIfPreview.module.css";
import Dropdown from "./Dropdown";

export default function OnlyIfCondition({ decision, record, rows, onChange }: {
  decision: AnswerDecision;
  record: AnswerTableCase;
  rows: Recommendation[];
  onChange: (updater: (decision: AnswerDecision) => AnswerDecision) => void;
}): ReactNode {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const picker = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  if (decision.activation.type !== "onlyIf") return null;
  const selected = decision.activation.rows;
  const change = (id: string): void => onChange((current) => current.activation.type === "onlyIf" ? {
    ...current, activation: { ...current.activation, rows: current.activation.rows.includes(id)
      ? current.activation.rows.filter((rowId) => rowId !== id) : [...current.activation.rows, id] },
  } : current);
  const short = (id: string): string => id.replace(/^D/, "").replace(".O", ".");
  const text = (id: string): string => rows.find((row) => row.id === id)?.text || id;
  const close = (): void => { picker.current!.hidePopover(); trigger.current!.focus({ preventScroll: true }); };
  const linked = (id: string): ReactNode => <div className={styles.linked} key={id}>
    <span className={styles.number}>{short(id)}</span>
    <div className={styles.text}>
      <span className={styles.source}>{record.decisions.find((item) => item.recommendations.some((row) => row.id === id))?.question}</span>
      <span>{text(id)}</span>
    </div>
    <button className={styles.remove} aria-label={`Remove condition ${id} from ${decision.id}`} onClick={() => change(id)} type="button">×</button>
  </div>;
  return <section aria-label={`Condition for ${decision.id}`} className={styles.root} data-relationship-group="activation">
    <div className={styles.sentence}><strong>This decision is conditional. It applies only if the response includes <Dropdown
      aria-label={`Condition match for ${decision.id}`} className={styles.match} value={decision.activation.match ?? "any"}
      onChange={(event) => { const match = event.target.value as "any" | "all"; onChange((current) => current.activation.type === "onlyIf" ? { ...current, activation: { ...current.activation, match } } : current); }}
    ><option value="any">any</option><option value="all">all</option></Dropdown> of the following:</strong></div>
    <div className={styles.sourceList}>{selected.map(linked)}</div>
    {!selected.length && <p className={styles.empty}>Select at least one trigger recommendation.</p>}
    <button aria-label={`Add condition to ${decision.id}`} aria-controls={id} aria-expanded={open} aria-haspopup="dialog" className={styles.add} ref={trigger} type="button" onClick={() => {
      if (open) close();
      else { picker.current!.showPopover(); picker.current!.querySelector<HTMLButtonElement>("button")!.focus({ preventScroll: true }); }
    }}>Add condition</button>
    <div aria-label={`Which recommendations should trigger this condition for ${decision.id}?`} className={styles.picker} id={id} popover="auto" ref={picker} role="dialog"
      onToggle={(event) => setOpen(event.newState === "open")}
      onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); } }}>
      <div className={styles.pickerHeader}><h2>Which recommendations should trigger this condition?</h2><button aria-label="Close recommendation picker" className={styles.remove} onClick={close} type="button">×</button></div>
      <div className={styles.options}>
        {record.decisions.filter((source) => source.id !== decision.id).map((source) => <section key={source.id} aria-label={`Recommendations from ${source.id}`}>
          <h3>{source.id} · {source.question}</h3>
          {rows.filter((row) => source.recommendations.some((item) => item.id === row.id)).map((row) => <button aria-label={`Add ${short(row.id)}: ${row.text || row.id}`} className={styles.option} disabled={selected.includes(row.id)} key={row.id} onClick={() => { change(row.id); close(); }} type="button">
            <span className={styles.number}>{short(row.id)}</span><span>{row.text || row.id}</span>{selected.includes(row.id) && <span className={styles.added}>Added</span>}
          </button>)}
        </section>)}
      </div>
    </div>
  </section>;
}

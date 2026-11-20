"use client";

import { useContext, useId, useState } from "react";
import type { ReactNode } from "react";
import { EvidenceSelectionContext } from "@/components/mc/EvidenceLinker";
import styles from "./EvidenceLinker.module.css";

export default function EvidenceMatch({ id, spanKeys, note, missing = false, children }: { id: string; spanKeys: string[]; note: ReactNode; missing?: boolean; children: ReactNode }) {
  const { active, dispatch } = useContext(EvidenceSelectionContext);
  const description = useId();
  const [focused, setFocused] = useState(false);
  const selected = active?.id === id;
  const showNote = selected && focused;
  const target = { id, keys: spanKeys };
  return (
    <div className={styles.match} data-evidence-selected={selected ? "true" : undefined}
      onPointerEnter={() => dispatch({ type: "hover", target })} onPointerLeave={() => dispatch({ type: "leave", id })}>
      <button aria-describedby={description} className={styles.row} data-evidence-match={id} type="button"
        onFocus={() => { setFocused(true); dispatch({ type: "focus", target }); }} onBlur={() => { setFocused(false); dispatch({ type: "blur", id }); }}
        onKeyDown={(event) => { if (event.key === "Escape") dispatch({ type: "dismiss" }); }}
        onClick={(event) => { event.currentTarget.focus(); dispatch({ type: "focus", target }); }}>
        {children}
      </button>
      <div aria-hidden={!showNote} className={styles.note} data-evidence-missing={missing ? "true" : undefined} id={description} inert={!showNote ? true : undefined} role="tooltip">{note}</div>
    </div>
  );
}

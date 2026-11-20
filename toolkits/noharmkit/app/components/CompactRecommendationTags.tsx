"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { RECOMMENDATION_TAGS, RECOMMENDATION_TAG_LABELS, RECOMMENDATION_TAG_DESCRIPTIONS } from "@/lib/answer-table";
import type { Recommendation, RecommendationTag } from "@/lib/answer-table";
import styles from "./CompactRecommendationTags.module.css";

const TAG_SHORTHAND: Record<RecommendationTag, string> = {
  diagnostic: "DX",
  medication: "TX",
  procedure: "PROC",
  counseling: "EDU",
  followUp: "F/U",
  none: "NA",
};

export default function CompactRecommendationTags({ row, onChange }: {
  row: Recommendation;
  onChange: (tags: RecommendationTag[]) => void;
}): ReactNode {
  const trigger = useRef<HTMLButtonElement>(null);
  const picker = useRef<HTMLDivElement>(null);
  const id = useId();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<CSSProperties>({});
  const selected = RECOMMENDATION_TAGS.filter((tag) => row.tags?.includes(tag));
  const toggle = (tag: RecommendationTag): void => onChange(RECOMMENDATION_TAGS.filter((candidate) => candidate === tag ? !selected.includes(tag) : selected.includes(candidate)));
  const updatePosition = (): void => {
    const rect = trigger.current!.getBoundingClientRect();
    const width = Math.min(384, window.innerWidth - 24);
    const height = picker.current!.offsetHeight;
    setPosition({ width, left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)), top: Math.max(12, rect.bottom + 8 + height <= window.innerHeight - 12 ? rect.bottom + 8 : rect.top - height - 8) });
  };
  useEffect(() => {
    if (!open) return;
    const reposition = (): void => updatePosition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => { window.removeEventListener("resize", reposition); window.removeEventListener("scroll", reposition, true); };
  }, [open]);

  const label = selected.length ? selected.map((tag) => RECOMMENDATION_TAG_LABELS[tag]).join(", ") : "No tags";
  return <>
    <button aria-label={`Edit tags for ${row.id}: ${label}`} aria-controls={id} aria-expanded={open}
      aria-haspopup="dialog" className={styles.assigned} ref={trigger} title={`Tags: ${label}`} type="button"
      onClick={() => {
        if (open) picker.current!.hidePopover();
        else {
          picker.current!.showPopover();
          updatePosition();
          picker.current!.querySelector<HTMLInputElement>("input")!.focus({ preventScroll: true });
        }
      }}>
      <span>{selected.length ? TAG_SHORTHAND[selected[0]] : "Tag"}</span>
      {selected.length > 1 && <span className={styles.additional}>+{selected.length - 1}</span>}
    </button>
    <div className={styles.picker} id={id} popover="auto" ref={picker} role="dialog" aria-label={`Tags for ${row.id}`} style={position}
      onToggle={(event) => setOpen(event.newState === "open")}
      onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); picker.current!.hidePopover(); trigger.current!.focus(); } }}>
      <fieldset>
        <legend>Tags</legend>
        <p>Descriptive only. Select all that apply.</p>
        {RECOMMENDATION_TAGS.map((tag) => <label key={tag}>
          <input type="checkbox" checked={selected.includes(tag)} onChange={() => toggle(tag)} />
          <span><strong>{RECOMMENDATION_TAG_LABELS[tag]}</strong><small>{RECOMMENDATION_TAG_DESCRIPTIONS[tag]}</small></span>
        </label>)}
      </fieldset>
    </div>
  </>;
}

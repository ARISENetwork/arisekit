"use client";

import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactElement } from "react";
import { createPortal } from "react-dom";
import styles from "./DatasetButtonReview.module.css";

type Position = { x: number; y: number };
type Choice = { id: string; label: string; description: string };
type ReviewProps = {
  title: string;
  label: string;
  batch: string;
  choices: readonly Choice[];
  baseline: string;
  initialChoice?: string;
  choiceDetails?: string;
  portalTarget?: HTMLElement | null;
  onChange: (value: string) => void;
};

function ReviewPanel({ title, label, batch, choices, baseline, initialChoice, choiceDetails, portalTarget, onChange }: ReviewProps): ReactElement {
  const bodyId = useId();
  const [treatment, setTreatment] = useState(initialChoice ?? choices[0].id);
  const [original, setOriginal] = useState(false);
  const [collapsed, setCollapsed] = useState(true);
  const [position, setPosition] = useState<Position>({ x: Math.max(12, window.innerWidth - 324), y: 166 });
  const [copyStatus, setCopyStatus] = useState("");
  const [copyFallback, setCopyFallback] = useState("");
  const panel = useRef<HTMLElement>(null);
  const collapseButton = useRef<HTMLButtonElement>(null);
  const drag = useRef<{ pointer: number; x: number; y: number; origin: Position } | null>(null);
  const effective = original ? baseline : treatment;
  useEffect(() => { onChange(effective); }, [effective, onChange]);
  const clamp = useCallback((point: Position): Position => {
    const rect = panel.current?.getBoundingClientRect();
    return {
      x: Math.min(Math.max(12, point.x), Math.max(12, window.innerWidth - (rect?.width ?? 300) - 12)),
      y: Math.min(Math.max(12, point.y), Math.max(12, window.innerHeight - (rect?.height ?? 56) - 12)),
    };
  }, []);
  useEffect(() => {
    const fit = (): void => setPosition(point => clamp(point));
    fit();
    const observer = new ResizeObserver(fit);
    if (panel.current) observer.observe(panel.current);
    window.addEventListener("resize", fit);
    return () => { observer.disconnect(); window.removeEventListener("resize", fit); };
  }, [clamp, portalTarget]);
  const bodyRef = useCallback((element: HTMLDivElement | null): void => { if (element) element.inert = collapsed; }, [collapsed]);
  function moveWithKeys(event: KeyboardEvent<HTMLButtonElement>): void {
    const directions: Record<string, Position> = { ArrowLeft: { x: -1, y: 0 }, ArrowRight: { x: 1, y: 0 }, ArrowUp: { x: 0, y: -1 }, ArrowDown: { x: 0, y: 1 } };
    const direction = directions[event.key];
    if (!direction) return;
    event.preventDefault();
    const distance = event.shiftKey ? 40 : 10;
    setPosition(point => clamp({ x: point.x + direction.x * distance, y: point.y + direction.y * distance }));
  }
  function beginDrag(event: PointerEvent<HTMLButtonElement>): void {
    if (event.button !== 0) return;
    drag.current = { pointer: event.pointerId, x: event.clientX, y: event.clientY, origin: position };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function moveDrag(event: PointerEvent<HTMLButtonElement>): void {
    const current = drag.current;
    if (!current || current.pointer !== event.pointerId) return;
    setPosition(clamp({ x: current.origin.x + event.clientX - current.x, y: current.origin.y + event.clientY - current.y }));
  }
  async function copyChoices(): Promise<void> {
    const choice = choices.find(item => item.id === treatment)!;
    const text = `Review: ${window.location.pathname}\nBatch: ${batch}\n${title}: ${choice.label}${choiceDetails ? `\n${choiceDetails}` : ""}\nShowing: ${original ? "original" : "preview"}`;
    try { await navigator.clipboard.writeText(text); setCopyStatus("Choices copied."); setCopyFallback(""); }
    catch { setCopyFallback(text); setCopyStatus("Select and copy the choices below."); }
  }
  return createPortal(<aside ref={panel} className={styles.panel} aria-label={label} style={{ left: position.x, top: position.y }} onKeyDown={event => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setCollapsed(true); collapseButton.current?.focus(); }
    }}>
      <div className={styles.panelHeader}>
        <button type="button" className={styles.move} aria-label="Move review panel" title="Drag, or use arrow keys to move" onKeyDown={moveWithKeys} onPointerDown={beginDrag} onPointerMove={moveDrag} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
          <svg aria-hidden="true" width="14" height="18" viewBox="0 0 14 18" fill="currentColor"><circle cx="4" cy="4" r="1" /><circle cx="10" cy="4" r="1" /><circle cx="4" cy="9" r="1" /><circle cx="10" cy="9" r="1" /><circle cx="4" cy="14" r="1" /><circle cx="10" cy="14" r="1" /></svg>
        </button>
        <strong>{title}</strong>
        <button ref={collapseButton} type="button" aria-expanded={!collapsed} aria-controls={bodyId} onClick={() => setCollapsed(value => !value)}>{collapsed ? "Expand" : "Collapse"}</button>
      </div>
      <div ref={bodyRef} id={bodyId} className={styles.body} data-collapsed={collapsed}>
        <div className={styles.inner}>
          <div className={styles.choices} role="group" aria-label={title}>{choices.map(item => <button key={item.id} type="button" aria-pressed={treatment === item.id} onClick={() => { setTreatment(item.id); setOriginal(false); setCopyStatus(""); setCopyFallback(""); }}>{item.label}</button>)}</div>
          <p>{original ? "Showing the accepted interface." : choices.find(item => item.id === treatment)!.description}</p>
          <button type="button" className={styles.compare} onClick={() => setOriginal(value => !value)}>{original ? "Return to preview" : "Show original"}</button>
          <div className={styles.tools}>
            <button type="button" onClick={() => void copyChoices()}>Copy choices</button>
            <button type="button" onClick={() => setPosition(clamp({ x: window.innerWidth - 324, y: 166 }))}>Reset position</button>
          </div>
          <p className={styles.note}>Preview only. Choices reset on reload. Drag the grip or use its arrow keys to move this panel.</p>
          <span className={styles.status} role="status">{copyStatus}</span>
          {copyFallback && <textarea aria-label="Choices to copy" readOnly value={copyFallback} />}
        </div>
      </div>
    </aside>, portalTarget ?? document.body);
}

export default function FloatingReviewPanel(props: ReviewProps): ReactElement | null {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  return mounted ? <ReviewPanel {...props} /> : null;
}

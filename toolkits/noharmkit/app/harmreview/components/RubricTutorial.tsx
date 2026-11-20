"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import RubricEditor from "@/harmreview/components/RubricEditor";
import type { TutorialControls } from "@/harmreview/components/RubricEditor";
import { findItem, TUTORIAL_RECORD, TUTORIAL_SOURCE, TUTORIAL_STEPS } from "@/harmreview/lib/rubric-tutorial";
import type { StepCopy } from "@/harmreview/lib/rubric-tutorial";
import { placePopup, scrollDelta, unionBox } from "@/harmreview/lib/tutorial-placement";
import type { Box, Placement, View } from "@/harmreview/lib/tutorial-placement";
import styles from "./RubricTutorial.module.css";

// The hole sits a little outside what it highlights.
const PAD = 6;
const HEADER_INSET = 64;
// Longer than a card takes to expand, so the scroll lands where the target ends up.
const EXPAND_MS = 240;
const ADVANCE_MS = 450;
const FOCUSABLE = 'button:not([disabled]), textarea, a[href], [tabindex="0"]';

const reducedMotion = (): boolean => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const view = (): View => ({ width: window.innerWidth, height: window.innerHeight, topInset: HEADER_INSET });

function measure(selector: string | undefined): Box | null {
  if (!selector) return null;
  return unionBox(Array.from(document.querySelectorAll(selector), (element) => element.getBoundingClientRect()));
}

const pad = (box: Box): Box => ({ top: box.top - PAD, left: box.left - PAD, width: box.width + 2 * PAD, height: box.height + 2 * PAD });
const same = (a: Box | null, b: Box | null): boolean => a === b || (!!a && !!b && Math.abs(a.top - b.top) < 0.5 && Math.abs(a.left - b.left) < 0.5 && Math.abs(a.width - b.width) < 0.5 && Math.abs(a.height - b.height) < 0.5);
const samePlace = (a: Placement | null, b: Placement): boolean => !!a && a.side === b.side && Math.abs(a.top - b.top) < 0.5 && Math.abs(a.left - b.left) < 0.5 && Math.abs(a.caret - b.caret) < 0.5;

// On /tutorial?edit, each popup's text is a form whose changes save into data/tutorial/copy.json. A blank line
// separates paragraphs.
interface Draft { caption: string; heading: string; body: string }
const toDraft = (copy: StepCopy): Draft => ({ caption: copy.caption, heading: copy.heading, body: copy.text.join("\n\n") });
const toCopy = (draft: Draft): StepCopy => ({ caption: draft.caption.trim(), heading: draft.heading.trim(), text: draft.body.split(/\n\s*\n/).map((line) => line.trim()).filter(Boolean) });
const sameCopy = (a: StepCopy, b: StepCopy): boolean => a.caption === b.caption && a.heading === b.heading && a.text.join("\n") === b.text.join("\n");

// **text** in the copy file shows bold, for the names of things on screen.
const bolded = (line: string): ReactNode => line.split("**").map((part, index) => (index % 2 ? <strong key={index}>{part}</strong> : part));

function EditBox({ label, value, onChange, onSave }: { label: string; value: string; onChange: (value: string) => void; onSave: () => void }): ReactNode {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [value]);
  return <textarea aria-label={label} className={styles.edit} ref={ref} rows={1} value={value} onBlur={onSave} onChange={(event) => onChange(event.target.value)} />;
}

function CapIcon() {
  return <svg aria-hidden="true" fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="16"><path d="M21 10 12 5 3 10l9 5 9-5Z" /><path d="M7 12.5V17c0 1 2.2 2.5 5 2.5s5-1.5 5-2.5v-4.5" /></svg>;
}

// The dim, the popup and the glow, over the real editor. Only the highlighted part takes clicks, so every step acts
// on the editor itself; nothing here reaches the server.
function TutorialOverlay({ record, openIds, setOpenIds, updateRecord, onRestart, editable }: TutorialControls & { onRestart: () => void; editable: boolean }): ReactNode {
  const ids = useId();
  const popup = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [index, setIndex] = useState(0);
  const [active, setActive] = useState(true);
  const [hole, setHole] = useState<Box | null>(null);
  const [cueBox, setCueBox] = useState<Box | null>(null);
  const [place, setPlace] = useState<Placement | null>(null);
  // A step's popup does not slide across the page: it leaves at once and fades up in its new place.
  const [arrived, setArrived] = useState(true);
  const [moving, setMoving] = useState(false);
  const [typing, setTyping] = useState(false);
  const step = TUTORIAL_STEPS[index];
  const last = index === TUTORIAL_STEPS.length - 1;
  const state = { record, openIds };
  const done = step.done?.(state) ?? true;
  const cue = active && !done ? step.cue?.(state) : undefined;
  const hint = !done ? step.hint?.(state) ?? null : null;
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saved, setSaved] = useState<{ id: string; message: string } | null>(null);
  const draft = drafts[step.id] ?? toDraft(step);
  const editDraft = (change: Partial<Draft>): void => setDrafts((current) => ({ ...current, [step.id]: { ...(current[step.id] ?? toDraft(step)), ...change } }));
  const saveDraft = async (): Promise<void> => {
    const copy = toCopy(draft);
    if (sameCopy(copy, step)) return;
    const id = step.id;
    setSaved({ id, message: "Saving" });
    const response = await fetch("/api/tutorial-copy", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, copy }) });
    const result = (await response.json()) as { error?: string };
    setSaved({ id, message: response.ok ? "Saved to data/tutorial/copy.json" : result.error ?? `Save failed (${response.status})` });
  };

  // The step whose required action was seen undone; only that step moves on by itself. Only navigation clears it,
  // so when a copy save reloads the code and every effect re-runs, the pending advance is set again.
  const armed = useRef<number | null>(null);
  const advance = useCallback(() => { armed.current = null; setIndex((current) => Math.min(current + 1, TUTORIAL_STEPS.length - 1)); }, []);

  // Each step opens the cards it needs, shows its target with the popup, and takes focus so the step is read.
  useLayoutEffect(() => {
    setOpenIds(step.open);
    setArrived(false);
    setMoving(true);
    heading.current?.focus({ preventScroll: true });
    let second = 0;
    const first = requestAnimationFrame(() => { second = requestAnimationFrame(() => setArrived(true)); });
    const settled = setTimeout(() => setMoving(false), 520);
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); clearTimeout(settled); };
  }, [step, setOpenIds]);

  useEffect(() => {
    const selector = step.target;
    if (!selector) { window.scrollTo({ top: 0, behavior: reducedMotion() ? "instant" : "smooth" }); return; }
    if (!active) return;
    const timer = setTimeout(() => {
      const target = measure(selector);
      if (!target || !popup.current) return;
      // Sticky parts do not move with the page.
      if (document.querySelector(selector)?.closest("aside, [data-rubric] header")) return;
      const delta = scrollDelta(pad(target), popup.current.offsetHeight, view());
      if (Math.abs(delta) > 1) window.scrollBy({ top: delta, behavior: reducedMotion() ? "instant" : "smooth" });
    }, EXPAND_MS);
    return () => clearTimeout(timer);
  }, [active, step]);

  // Follows the target every frame: scrolling, expanding cards and re-sorting rows all move it.
  useEffect(() => {
    if (!active) return;
    let frame = 0;
    const tick = (): void => {
      const measured = measure(step.target);
      const nextHole = measured && pad(measured);
      const nextCue = measure(cue);
      setHole((current) => (same(current, nextHole) ? current : nextHole));
      setCueBox((current) => (same(current, nextCue) ? current : nextCue));
      if (popup.current) {
        const size = { width: popup.current.offsetWidth, height: popup.current.offsetHeight };
        const next = placePopup(nextHole, size, view());
        setPlace((current) => (samePlace(current, next) ? current : next));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active, cue, step.target]);

  // A required action moves on by itself once done; a step revisited with it already done waits for Next, so Back never bounces.
  useEffect(() => {
    if (!done) { armed.current = index; return; }
    if (armed.current !== index || !active) return;
    const timer = setTimeout(advance, reducedMotion() ? 0 : ADVANCE_MS);
    return () => clearTimeout(timer);
  }, [active, advance, done, index]);

  // The example writes itself in with an uneven rhythm, so it reads as typed; leaving early fills the rest.
  const types = step.types;
  useEffect(() => {
    if (!types || findItem(record, types.item)?.text) return;
    const write = (text: string): void => updateRecord((current) => ({ ...current, decisions: current.decisions.map((criterion) => ({ ...criterion, recommendations: criterion.recommendations.map((item) => (item.id === types.item ? { ...item, text } : item)) })) }));
    if (reducedMotion()) { write(types.text); return; }
    setTyping(true);
    let shown = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = (): void => {
      shown += 1;
      write(types.text.slice(0, shown));
      if (shown < types.text.length) timer = setTimeout(tick, 14 + Math.random() * 22);
      else setTyping(false);
    };
    timer = setTimeout(tick, 350);
    return () => { clearTimeout(timer); setTyping(false); if (shown < types.text.length) write(types.text); };
    // Runs once per step; the record it writes must not restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [types, updateRecord]);

  // Focus stays in the popup and the highlighted part; the Guide and open menus may also take it.
  useEffect(() => {
    if (!active) return;
    const guard = (event: FocusEvent): void => {
      const element = event.target;
      if (!(element instanceof Element) || element.closest('dialog, [role="dialog"], [role="listbox"]')) return;
      if (step.target && element.closest(step.target)) return;
      heading.current?.focus({ preventScroll: true });
    };
    document.addEventListener("focusin", guard);
    return () => document.removeEventListener("focusin", guard);
  }, [active, step.target]);

  const canAdvance = done && !typing;
  const next = useCallback((): void => { if (!canAdvance) return; if (last) setActive(false); else advance(); }, [advance, canAdvance, last]);
  const back = useCallback((): void => { armed.current = null; setIndex((current) => Math.max(current - 1, 0)); }, []);

  // Removing a row could strand a later step, so the X buttons wait until the walkthrough ends.
  useEffect(() => {
    if (!active) return;
    const guard = (event: MouseEvent): void => {
      if (event.target instanceof Element && event.target.closest('[aria-label^="Remove "]')) { event.preventDefault(); event.stopPropagation(); }
    };
    document.addEventListener("click", guard, true);
    return () => document.removeEventListener("click", guard, true);
  }, [active]);

  // The arrows step from anywhere on the page, except controls that use them and the Guide.
  useEffect(() => {
    if (!active) return;
    const arrows = (event: globalThis.KeyboardEvent): void => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      if (event.target instanceof Element && event.target.closest('textarea, input, [role="combobox"], [role="listbox"], [aria-modal="true"]')) return;
      event.preventDefault();
      if (event.key === "ArrowRight") next(); else back();
    };
    document.addEventListener("keydown", arrows);
    return () => document.removeEventListener("keydown", arrows);
  }, [active, back, next]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) return;
    if (event.key === "Enter" && !(event.target instanceof HTMLButtonElement)) { event.preventDefault(); next(); return; }
    if (event.key !== "Tab" || event.shiftKey || !step.target) return;
    // Tab goes from the popup's last button into the highlighted part.
    const controls = Array.from(popup.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (document.activeElement !== controls.at(-1)) return;
    const entry = Array.from(document.querySelectorAll(step.target)).flatMap((part) => Array.from(part.querySelectorAll<HTMLElement>(FOCUSABLE))).find((element) => !element.closest("[inert]"));
    if (entry) { event.preventDefault(); entry.focus({ preventScroll: true }); }
  };

  if (!active) {
    return <aside aria-label="Tutorial finished" className={styles.finished}>
      <p>You can keep exploring. Nothing here is saved.</p>
      <button type="button" onClick={onRestart}>Start over</button>
    </aside>;
  }

  // A finished action takes no more clicks, so a double click on + Add adds one row.
  const blockers = hole && !(step.done && done) ? [
    { top: 0, left: 0, right: 0, height: Math.max(0, hole.top) },
    { top: hole.top + hole.height, left: 0, right: 0, bottom: 0 },
    { top: hole.top, left: 0, width: Math.max(0, hole.left), height: hole.height },
    { top: hole.top, left: hole.left + hole.width, right: 0, height: hole.height },
  ] : [{ top: 0, left: 0, right: 0, bottom: 0 }];
  const shown = arrived && place !== null;
  return <div data-tutorial>
    {blockers.map((style, position) => <div aria-hidden="true" className={styles.blocker} key={position} style={style} />)}
    {hole && <div aria-hidden="true" className={styles.hole} data-moving={moving || undefined} style={hole} />}
    {cueBox && <div aria-hidden="true" className={styles.cue} style={cueBox} />}
    <div
      aria-describedby={`${ids}-text`}
      aria-labelledby={`${ids}-caption ${ids}-heading`}
      className={styles.popup}
      data-shown={shown || undefined}
      data-side={place?.side}
      onKeyDown={onKeyDown}
      ref={popup}
      role="dialog"
      style={{ top: place?.top ?? 0, left: place?.left ?? 0, ["--caret" as string]: `${place?.caret ?? 0}px` }}
    >
      <div className={styles.card}>
        <p className={styles.caption} id={`${ids}-caption`}>
          <CapIcon />
          {editable
            ? <input aria-label="Caption" className={styles.editCaption} value={draft.caption} onBlur={() => void saveDraft()} onChange={(event) => editDraft({ caption: event.target.value })} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} />
            : <span>{step.caption}</span>}
          {index > 0 && <span className={styles.count}>Step {index} of {TUTORIAL_STEPS.length - 1}</span>}
        </p>
        <div className={styles.body}>
          {/* Focus lands here on every step so screen readers read it; it is programmatic, so no ring. */}
          <h2 id={`${ids}-heading`} ref={heading} tabIndex={-1}>{editable ? <EditBox label="Heading" value={draft.heading} onChange={(heading) => editDraft({ heading })} onSave={() => void saveDraft()} /> : step.heading}</h2>
          <div id={`${ids}-text`}>{editable
            ? <EditBox label="Text; a blank line starts a new paragraph" value={draft.body} onChange={(body) => editDraft({ body })} onSave={() => void saveDraft()} />
            : step.text.map((line) => <p key={line}>{bolded(line)}</p>)}</div>
          {editable && <p className={styles.editNote} role="status">{saved?.id === step.id ? saved.message : "Editing: click any text to change it. A blank line starts a new paragraph; **text** shows bold."}</p>}
          <p className={styles.hint} data-shown={hint !== null || undefined} role="status">{hint}</p>
          <div className={styles.actions}>
            <button className={styles.exit} type="button" onClick={() => setActive(false)}>Exit</button>
            <button disabled={index === 0} type="button" onClick={back}>Back</button>
            <button className={styles.primary} disabled={!canAdvance} type="button" onClick={next}>{last ? "Finish" : "Next"}</button>
          </div>
        </div>
      </div>
    </div>
  </div>;
}

export default function RubricTutorial({ editable = false }: { editable?: boolean }): ReactNode {
  // Starting over remounts the editor, which restores the example rubric.
  const [run, setRun] = useState(0);
  return <RubricEditor
    caseId={TUTORIAL_RECORD.caseId}
    key={run}
    previewOnly
    tutorial={{ record: TUTORIAL_RECORD, source: TUTORIAL_SOURCE, overlay: (controls) => <TutorialOverlay {...controls} editable={editable} onRestart={() => setRun((current) => current + 1)} /> }}
  />;
}

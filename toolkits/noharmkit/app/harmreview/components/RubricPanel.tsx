"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import RubricGuide from "./RubricGuide";
import styles from "./RubricPanel.module.css";

export default function RubricPanel({ open, trigger, onClose }: {
  open: boolean;
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
      (trigger ?? document.querySelector<HTMLButtonElement>('[data-rubric] button[aria-controls="rubric-panel"]'))?.focus({ preventScroll: true });
    };
  }, [open, ready, trigger, onClose]);
  if (!ready) return null;
  return createPortal(
    <div aria-hidden={!open} className={styles.overlay} data-open={open} inert={!open ? true : undefined} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div
        aria-labelledby="rubric-tool-title"
        aria-modal="true"
        className={styles.panel}
        id="rubric-panel"
        ref={dialog}
        role="dialog"
      >
        <div className={styles.header}>
          <h2 id="rubric-tool-title">Guide</h2>
          <button aria-label="Close rubric tools" ref={closeButton} type="button" onClick={onClose}>
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m6 6 12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <div className={styles.views}>
          <div className={`${styles.view} ${styles.guideView}`} data-active id="rubric-guide">
            <RubricGuide />
          </div>
        </div>
      </div>
    </div>, trigger?.closest("dialog") ?? document.body,
  );
}

"use client";

import { useEffect, useState, type ReactNode } from "react";
import styles from "./TutorialEditorReturnGuide.module.css";

export default function TutorialEditorReturnGuide({ opened, onReturn }: { opened: boolean; onReturn: () => void }): ReactNode {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(false);
    if (!opened) return;
    const timer = window.setTimeout(() => setReady(true), 5000);
    return () => window.clearTimeout(timer);
  }, [opened]);
  const visible = opened && ready;

  return <aside className={styles.popover} data-open={visible} aria-hidden={!visible} inert={!visible} role="dialog" aria-label="Return to pipeline">
    <svg className={styles.pointer} aria-hidden="true" viewBox="0 0 18 10"><path d="M0 10 9 1 18 10" /></svg>
    <p>Now return to our pipeline.</p>
    <div className={styles.actions}>
      <button type="button" onClick={() => setReady(false)}>Keep Exploring</button>
      <button className={styles.primary} type="button" onClick={onReturn}>Return to Pipeline</button>
    </div>
  </aside>;
}

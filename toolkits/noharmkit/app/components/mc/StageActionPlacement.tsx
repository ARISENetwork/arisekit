"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import styles from "./StageActionPlacement.module.css";

export default function StageActionPlacement({ children, active = true }: { children: ReactNode; active?: boolean }) {
  const anchor = useRef<HTMLDivElement>(null);
  const [heading, setHeading] = useState<Element | null>(null);
  useEffect(() => {
    if (!active || !anchor.current) return;
    const element = anchor.current.closest("main") ?? anchor.current;
    const update = (): void => setHeading(element.querySelector("[data-stage-heading-actions]"));
    update();
    const observer = new MutationObserver(update);
    observer.observe(element, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [active]);
  if (!active) return <div className={styles.original}>{children}</div>;
  return <>
    <div className={styles.anchor} ref={anchor}>{!heading && children}</div>
    {heading && createPortal(<div data-stage-action-dock className={styles.heading}>{children}</div>, heading)}
  </>;
}

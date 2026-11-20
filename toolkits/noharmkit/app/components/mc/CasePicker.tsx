"use client";

import type { ReactNode } from "react";

import RoutePicker from "@/components/mc/RoutePicker";
import { useMotionNavigation } from "@/components/NavigationMotion";
import styles from "./CasePicker.module.css";

export default function CasePicker({ ids, current, hrefs, children, progress }: { ids: string[]; current: string; hrefs: Record<string, string>; children?: ReactNode; progress?: ReactNode }) {
  const navigate = useMotionNavigation();
  const i = ids.indexOf(current);
  const prev = ids[(i - 1 + ids.length) % ids.length];
  const next = ids[(i + 1) % ids.length];
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-mc-line bg-mc-surface px-2.5 py-2 shadow-mc">
      <button aria-label="Previous item" title="Previous item" className={`${styles.arrow} ${styles.previous}`} type="button" onClick={() => navigate(hrefs[prev])}>
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="m15 6-6 6 6 6" /></svg>
      </button>
      <RoutePicker id="mc-case" label="Dataset entry" options={ids.map((id) => ({ value: id, label: id.replace(/^Case(\d{3,})$/, "Case-$1"), href: hrefs[id] }))} value={current} />
      <button aria-label="Next item" title="Next item" className={`${styles.arrow} ${styles.next}`} type="button" onClick={() => navigate(hrefs[next])}>
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="m9 6 6 6-6 6" /></svg>
      </button>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{children}</div>
      {progress && <div data-stage-progress className="ml-auto flex flex-wrap items-center justify-end gap-3 text-[12.5px] text-mc-muted">{progress}</div>}
    </div>
  );
}

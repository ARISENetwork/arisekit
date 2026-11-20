"use client";

import { useId, useState } from "react";
import type { ReactNode } from "react";

// Opens and closes through the .group-content-wrapper transition in globals.css; closed content is inert.
export default function Reveal({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className="rounded-md border border-mc-line">
      <button aria-controls={id} aria-expanded={open} className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left" type="button" onClick={() => setOpen((v) => !v)}>
        <svg aria-hidden="true" className={`mt-1 h-3 w-3 shrink-0 text-mc-faint transition-transform duration-200 motion-reduce:transition-none ${open ? "rotate-90" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path d="m9 6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.4} />
        </svg>
        <span className="min-w-0 flex-1">{summary}</span>
      </button>
      <div className={`group-content-wrapper ${open ? "expanded" : ""}`} id={id} inert={!open ? true : undefined}>
        <div className="group-content-inner">
          <div className="px-3 pb-3">{children}</div>
        </div>
      </div>
    </div>
  );
}

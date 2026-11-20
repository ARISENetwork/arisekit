"use client";

import { useId, useState } from "react";

export default function ReviewDisclosure({ title, children, expanded }: { title: string; children: React.ReactNode; expanded?: boolean }) {
  const [override, setOverride] = useState<{ baseline: boolean; value: boolean } | null>(null);
  const baseline = Boolean(expanded);
  if (override && override.baseline !== baseline) setOverride(null);
  const open = override?.baseline === baseline ? override.value : baseline;
  const id = useId();
  return (
    <div className="border-t border-[hsl(var(--border))] py-2">
      <button aria-controls={id} aria-expanded={open} className="flex w-full items-center gap-2 rounded-md px-1 py-2 text-left text-sm font-semibold text-[hsl(var(--foreground))] transition-colors hover:bg-[hsl(var(--muted))] focus-visible:outline-2 focus-visible:outline-[hsl(var(--ring))]" onClick={() => setOverride({ baseline, value: !open })} type="button">
        <svg aria-hidden="true" className={`h-4 w-4 shrink-0 transition-transform duration-200 motion-reduce:transition-none ${open ? "rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.7" viewBox="0 0 20 20"><path d="m7 4 6 6-6 6" /></svg>
        {title}
      </button>
      <div aria-hidden={!open} className={`grid transition-[grid-template-rows,opacity] duration-200 motion-reduce:transition-none ${open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`} id={id} inert={!open ? true : undefined}>
        <div className="min-h-0 overflow-hidden"><div className="px-1 pb-3 pt-1">{children}</div></div>
      </div>
    </div>
  );
}

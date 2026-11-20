import type { ReactNode } from "react";

import Frame from "@/components/mc/Frame";
import type { NavData } from "@/components/mc/nav";
import type { Current } from "@/lib/caseset/current";
import { relativeTime } from "@/lib/caseset/routes";
import { STEP_KEYS } from "@/lib/caseset/steps";

export default function McShell({ current, children, showSyntheticNotice = true }: { current: Current; children: ReactNode; showSyntheticNotice?: boolean }) {
  const { bench } = current;
  const synthetic = bench.cases.some((c) => c.page.provenance.synthetic === true);
  const nav: NavData = {
    benchmark: bench.name,
    synthetic,
    benchmarks: current.names,
    titles: current.titles,
    dev: false,
    updatedLabel: bench.updatedAt ? relativeTime(bench.updatedAt, new Date()) : null,
    dots: Object.fromEntries(STEP_KEYS.map((k) => [k, bench.steps[k].dot])) as NavData["dots"],
  };
  return <Frame nav={nav}>
    {synthetic && showSyntheticNotice && <aside aria-label="Synthetic demo" className="mb-5 rounded-lg border border-mc-line bg-mc-accent-bg px-5 py-4 text-sm">
      <strong>Synthetic demo</strong>
      <p className="m-0 mt-1 text-mc-muted">These inputs, references, model responses, judgments, and scores are illustrative. They are not measured model performance or clinically validated content.</p>
    </aside>}
    {children}
  </Frame>;
}

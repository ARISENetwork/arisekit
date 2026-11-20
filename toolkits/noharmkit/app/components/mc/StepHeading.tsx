import { DATASET_DISCLAIMER, STEP_DESC, STEP_NAMES, STEP_NUMBERS } from "@/components/mc/nav";
import type { StepKey } from "@/lib/caseset/steps";
import type { ReactNode } from "react";

// actions sit left of the docked stage actions, so Next stays last in the row.
export default function StepHeading({ step, description, actions }: { step: StepKey; description?: string; actions?: ReactNode }) {
  return (
    <div className="grid min-w-0 flex-1 grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-1">
      <span className="grid h-7 w-7 place-items-center rounded-md bg-mc-accent-bg text-sm font-semibold text-mc-accent">{STEP_NUMBERS[step]}</span>
      <h1 className="m-0 text-[28px] font-semibold leading-tight tracking-[-0.035em]">{STEP_NAMES[step]}</h1>
      <p className="col-start-2 col-end-4 m-0 text-mc-muted">{description ?? STEP_DESC[step]}{step === "cases" && <> <strong>{DATASET_DISCLAIMER}</strong></>}</p>
      <div className="col-start-3 row-start-1 flex items-center gap-2">{actions}<div data-stage-heading-actions /></div>
    </div>
  );
}

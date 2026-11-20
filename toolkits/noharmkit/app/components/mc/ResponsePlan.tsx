"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import ResponsePromptPicker, { useChosenPrompt } from "./ResponsePromptPicker";
import { Card } from "./ui";
import styles from "./ResponsePlan.module.css";

const BUTTON = "rounded-md border border-mc-line-strong bg-mc-surface px-3 py-1 text-xs font-medium text-mc-ink transition-colors hover:bg-mc-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent motion-reduce:transition-none";

// The response plan at a glance; Change opens the prompt and the model checklist.
export default function ResponsePlan({ project, models, trials, promptless, checklist }: { project: string; models: string[]; trials: number; promptless: boolean; checklist: ReactNode }): ReactNode {
  const prompt = useChosenPrompt();
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  return <>
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-mc-line px-4 py-2.5">
        <h2 className="m-0 text-sm font-semibold">Plan</h2>
        <button className={`${BUTTON} ml-auto`} type="button" aria-haspopup="dialog" onClick={() => setOpen(true)}>Change</button>
      </div>
      <dl className="m-0 grid px-4 py-3 grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
        <dt className="text-mc-muted">Models</dt>
        <dd className="m-0">{models.length ? models.map((model) => <span className="block break-words" key={model}>{model}</span>) : <span className="text-mc-muted">None yet</span>}</dd>
        {!promptless && <><dt className="text-mc-muted">Prompt</dt><dd className="m-0">{prompt?.name ?? "None"}</dd></>}
        <dt className="text-mc-muted">Trials</dt>
        <dd className="m-0">{trials}</dd>
      </dl>
    </Card>
    <dialog ref={dialog} aria-labelledby={titleId} className={styles.dialog} onCancel={(event) => { event.preventDefault(); setOpen(false); }}>
      <div className="flex items-start justify-between gap-4">
        <h2 className="m-0 text-lg font-semibold" id={titleId}>Change plan</h2>
        <button className={BUTTON} type="button" onClick={() => setOpen(false)}>Close</button>
      </div>
      <div className="mt-4 flex flex-col gap-4">
        {!promptless && <section className="flex flex-col gap-2"><ResponsePromptPicker project={project} /></section>}
        <section className="flex flex-col gap-2"><h3 className="m-0 text-sm font-semibold">Models to test</h3>{checklist}</section>
      </div>
    </dialog>
  </>;
}

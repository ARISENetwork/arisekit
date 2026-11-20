"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { toolkitPrompt } from "@/lib/toolkit-prompt";

// The prompt text is selectable, so a failed clipboard write still leaves a way to copy it.
export default function PromptBox({ prompt, lead = "Ask your agent:", displayPrompt, copyLabel = "Copy", copyButtonTarget, miniCopy = false }: { prompt: string; lead?: string; displayPrompt?: string; copyLabel?: string; copyButtonTarget?: string; miniCopy?: boolean }) {
  const scopedPrompt = toolkitPrompt(prompt);
  const [copyTarget, setCopyTarget] = useState<HTMLElement | null>(null);
  useEffect(() => { setCopyTarget(copyButtonTarget ? document.getElementById(copyButtonTarget) : null); }, [copyButtonTarget]);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const copy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(scopedPrompt);
      setCopied(true);
      setCopyFailed(false);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
      setCopyFailed(true);
    }
  };
  const copyButton = <button className="shrink-0 rounded-md border border-mc-line-strong bg-mc-surface px-2.5 py-1 text-xs font-medium text-mc-ink transition-colors hover:border-mc-ink" type="button" onClick={() => { void copy(); }}>
    {copied ? "Copied" : copyLabel}
  </button>;
  return (
    <div className="relative rounded-lg border border-mc-line bg-mc-surface-2 p-3 text-sm">
      <p className={`m-0 text-mc-muted${miniCopy ? " pr-7" : ""}`}>{lead}</p>
      {miniCopy && <button data-mini-copy aria-label={copied ? "Copied" : copyLabel} title={copied ? "Copied" : copyLabel} className="absolute right-2 top-2 rounded border border-mc-line bg-mc-surface text-mc-ink" type="button" onClick={() => { void copy(); }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{copied ? <path d="m5 12 4 4L19 6" /> : <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4" /></>}</svg>
      </button>}
      <div className="mt-2 flex items-start gap-2">
        <p className="m-0 min-w-0 flex-1 select-all break-words font-mc-mono text-[13px]">{copyFailed ? scopedPrompt : displayPrompt ?? prompt}</p>
        {copyButtonTarget ? copyTarget && createPortal(copyButton, copyTarget) : copyButton}
      </div>
    </div>
  );
}

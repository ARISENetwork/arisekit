"use client";

import { createContext, useContext, useReducer } from "react";
import type { Dispatch, HTMLAttributes, ReactNode } from "react";

import { activeEvidence, EMPTY_EVIDENCE_SELECTION, evidenceSelection } from "@/lib/caseset/evidence-selection";
import type { EvidenceEvent, EvidenceTarget } from "@/lib/caseset/evidence-selection";

export const EvidenceSelectionContext = createContext<{ active: EvidenceTarget | null; dispatch: Dispatch<EvidenceEvent> }>({ active: null, dispatch: () => {} });

export default function EvidenceLinker({ children }: { children: ReactNode }) {
  const [selection, dispatch] = useReducer(evidenceSelection, EMPTY_EVIDENCE_SELECTION);
  return <EvidenceSelectionContext value={{ active: activeEvidence(selection), dispatch }}>{children}</EvidenceSelectionContext>;
}

export function EvidenceMark({ spanKeys, kind, ...props }: HTMLAttributes<HTMLElement> & { spanKeys: string[]; kind: string }) {
  const { active } = useContext(EvidenceSelectionContext);
  const selected = active?.keys.some((key) => spanKeys.includes(key)) ?? false;
  const tone = kind === "unmapped" ? "llm" : "accent";
  return <mark {...props} className="rounded-sm text-mc-ink outline outline-1 outline-transparent outline-offset-1 transition-[background-color,outline-color] duration-150 motion-reduce:duration-100"
    data-evidence-kind={kind} data-evidence-active={selected ? "true" : undefined}
    style={{ backgroundColor: selected ? `color-mix(in srgb, var(--mc-${tone}) 24%, var(--mc-surface))` : `var(--mc-${tone}-bg)`, outlineColor: selected ? `var(--mc-${tone})` : "transparent" }} />;
}

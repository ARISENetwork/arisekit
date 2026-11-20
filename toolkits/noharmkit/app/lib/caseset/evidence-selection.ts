export interface EvidenceTarget { id: string; keys: string[] }
export interface EvidenceSelection { hovered: EvidenceTarget | null; focused: EvidenceTarget | null; mode: "hover" | "focus" }
export type EvidenceEvent = { type: "hover" | "focus"; target: EvidenceTarget } | { type: "leave" | "blur"; id: string } | { type: "dismiss" };

export const EMPTY_EVIDENCE_SELECTION: EvidenceSelection = { hovered: null, focused: null, mode: "hover" };

export function evidenceSelection(state: EvidenceSelection, event: EvidenceEvent): EvidenceSelection {
  if (event.type === "dismiss") return EMPTY_EVIDENCE_SELECTION;
  if (event.type === "hover") return { ...state, hovered: event.target, mode: "hover" };
  if (event.type === "focus") return { ...state, focused: event.target, mode: "focus" };
  if (event.type === "leave") return state.hovered?.id === event.id ? { ...state, hovered: null } : state;
  if (event.type === "blur") return state.focused?.id === event.id ? { ...state, focused: null } : state;
  return state;
}

export function activeEvidence(state: EvidenceSelection): EvidenceTarget | null {
  return state.mode === "focus" ? state.focused ?? state.hovered : state.hovered ?? state.focused;
}

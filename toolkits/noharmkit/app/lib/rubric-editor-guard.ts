export interface RubricEditorStatus {
  dirty: boolean;
  saving: boolean;
  error: string | null;
  canSave: boolean;
}

export interface RubricEditorController extends RubricEditorStatus {
  save: () => Promise<boolean>;
}

export async function saveRubricBeforeLeaving(editor: RubricEditorController | null): Promise<boolean> {
  if (!editor || editor.saving) return false;
  if (!editor.dirty) return true;
  if (!editor.canSave) return false;
  return editor.save();
}

export function isLeavingRubricLink(href: string, current: string, target: string, download: boolean): boolean {
  if (download || (target && target !== "_self")) return false;
  const next = new URL(href, current);
  const previous = new URL(current);
  if (!/^https?:$/.test(next.protocol)) return false;
  return next.origin !== previous.origin || next.pathname !== previous.pathname || next.search !== previous.search;
}

export interface RubricHistoryNavigation extends EventTarget {
  traverseTo(key: string): unknown;
}

interface RubricHistoryEvent extends Event {
  navigationType: string;
  destination: { key: string; url: string; sameDocument: boolean };
}

export function guardRubricHistory(navigation: RubricHistoryNavigation | undefined, currentHref: () => string, hasEdits: () => boolean, requestLeave: (action: () => void) => void): () => void {
  if (!navigation) return () => {};
  const navigate = (event: Event): void => {
    const attempt = event as RubricHistoryEvent;
    if (attempt.navigationType !== "traverse" || !attempt.destination.sameDocument || !attempt.cancelable || !hasEdits()) return;
    if (!isLeavingRubricLink(attempt.destination.url, currentHref(), "", false)) return;
    attempt.preventDefault();
    requestLeave(() => { navigation.traverseTo(attempt.destination.key); });
  };
  navigation.addEventListener("navigate", navigate);
  return () => navigation.removeEventListener("navigate", navigate);
}

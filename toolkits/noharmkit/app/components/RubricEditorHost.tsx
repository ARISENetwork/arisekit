"use client";

import { createContext, useCallback, useContext, useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { AuthoringTiming } from "@/harmreview/lib/rubric";
import type { TextV2Case } from "@/harmreview/lib/rubric-text-v2";
import type { RubricEditorController } from "@/lib/rubric-editor-guard";

export const RubricEditorHost = createContext<((editor: RubricEditorController | null) => void) | null>(null);

export function useRubricEditorHost({ dirty, saving, canSave, error, save }: RubricEditorController): void {
  const report = useContext(RubricEditorHost);
  const latestSave = useRef(save);
  useLayoutEffect(() => { latestSave.current = save; });
  const saveCurrent = useCallback((): Promise<boolean> => latestSave.current(), []);
  useLayoutEffect(() => { report?.({ dirty, saving, canSave, error, save: saveCurrent }); }, [report, dirty, saving, canSave, error, saveCurrent]);
  useLayoutEffect(() => () => { report?.(null); }, [report]);
}

// What the toolkit supplies to the noharm-science editor it syncs (app/harmreview/components/RubricEditor.tsx):
// project storage instead of /api/rubric, the project's pinned validation, and its header tags and notices.
export interface TextV2EditorHost<Loaded> {
  reviewerId: string | null;
  load: () => Promise<Loaded>;
  // Reset: the rubric the reviewer's copy started from.
  loadOriginal: () => Promise<Loaded>;
  save: (loaded: Loaded, timing: AuthoringTiming) => Promise<{ message: string; update?: Partial<Loaded> }>;
  validate: (record: TextV2Case) => { errors: string[]; warnings: string[] };
  canSave?: (loaded: Loaded) => boolean;
  headerTags?: (loaded: Loaded | null) => ReactNode;
  banner?: (loaded: Loaded) => ReactNode;
  // Portable review files save by keeping or downloading a copy, so they keep an explicit Save button, named this,
  // instead of autosave.
  saveLabel?: string;
  // Where the editor's Tutorial button opens the walkthrough.
  tutorialHref?: string;
  onSaved?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  onSavingChange?: (saving: boolean) => void;
  // Shown before the first load finishes, so the editor also renders without one (static rendering).
  initial?: Loaded;
}

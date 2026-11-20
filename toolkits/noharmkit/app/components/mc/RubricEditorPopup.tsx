"use client";

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { createPortal } from "react-dom";
import styles from "./UtiTutorial.module.css";
import actionStyles from "./steps/RubricsStep.module.css";
import guardStyles from "./RubricEditorPopup.module.css";
import { RubricEditorHost } from "@/components/RubricEditorHost";
import { guardRubricHistory, isLeavingRubricLink, saveRubricBeforeLeaving, type RubricEditorController, type RubricEditorStatus, type RubricHistoryNavigation } from "@/lib/rubric-editor-guard";

const CLEAN: RubricEditorStatus = { dirty: false, saving: false, error: null, canSave: false };

export default function RubricEditorPopup({ children, className = actionStyles.openEditor }: { children: ReactNode; className?: string }): ReactNode {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const confirmation = useRef<HTMLDialogElement>(null);
  const editor = useRef<RubricEditorController | null>(null);
  const pending = useRef<(() => void) | null>(null);
  const afterClose = useRef<(() => void) | null>(null);
  const [savePending, setSavePending] = useState(false);
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [editorMounted, setEditorMounted] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [status, setStatus] = useState(CLEAN);
  const title = useId();
  const confirmTitle = useId();
  const confirmDescription = useId();
  const reportEditor = useCallback((current: RubricEditorController | null): void => {
    editor.current = current;
    setStatus(current ?? CLEAN);
  }, []);
  const finish = useCallback((action: () => void): void => {
    pending.current = null;
    afterClose.current = action;
    setConfirmOpen(false);
    setOpen(false);
    setEditorMounted(false);
  }, []);
  const requestLeave = useCallback((action: () => void): void => {
    const current = editor.current ?? CLEAN;
    setStatus(current);
    if (!current.dirty && !current.saving) { finish(action); return; }
    pending.current = () => finish(action);
    setConfirmOpen(true);
  }, [finish]);
  const close = (): void => requestLeave(() => router.refresh());
  const keepEditing = (): void => { pending.current = null; setConfirmOpen(false); };
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  useEffect(() => { if (confirmOpen) confirmation.current?.showModal(); else confirmation.current?.close(); }, [confirmOpen]);
  // Run navigation after the editor unmounts and removes its unload listener.
  useEffect(() => {
    if (editorMounted || !afterClose.current) return;
    const action = afterClose.current;
    afterClose.current = null;
    action();
  }, [editorMounted]);
  useEffect(() => {
    if (!editorMounted) return;
    const click = (event: MouseEvent): void => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!anchor) return;
      const url = new URL(anchor.href, window.location.href);
      const editorReturn = dialog.current?.contains(anchor) && url.origin === window.location.origin && (url.pathname === "/rubrics" || url.pathname === "/noharm/rubrics");
      const current = editor.current ?? CLEAN;
      if (!editorReturn && (!(current.dirty || current.saving) || !isLeavingRubricLink(anchor.href, window.location.href, anchor.target, anchor.hasAttribute("download")))) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      requestLeave(() => {
        if (editorReturn) router.refresh();
        else if (url.origin === window.location.origin) router.push(`${url.pathname}${url.search}${url.hash}`);
        else window.location.assign(url.href);
      });
    };
    const submit = (event: SubmitEvent): void => {
      if (!(event.target instanceof HTMLFormElement) || confirmation.current?.contains(event.target)) return;
      const current = editor.current ?? CLEAN;
      if (!current.dirty && !current.saving) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const form = event.target;
      requestLeave(() => HTMLFormElement.prototype.submit.call(form));
    };
    document.addEventListener("click", click, true);
    document.addEventListener("submit", submit, true);
    const stopHistoryGuard = guardRubricHistory((window as Window & { navigation?: RubricHistoryNavigation }).navigation, () => window.location.href, () => {
      const current = editor.current ?? CLEAN;
      return current.dirty || current.saving;
    }, requestLeave);
    return () => { stopHistoryGuard(); document.removeEventListener("click", click, true); document.removeEventListener("submit", submit, true); };
  }, [editorMounted, requestLeave, router]);
  const saveAndContinue = async (): Promise<void> => {
    const continuation = pending.current;
    setSavePending(true);
    try {
      if (await saveRubricBeforeLeaving(editor.current) && pending.current === continuation) continuation?.();
    } finally {
      setSavePending(false);
    }
  };
  return <>
    <button className={className} type="button" onClick={() => { setMounted(true); setEditorMounted(true); setOpen(true); }}>Open Rubric Editor</button>
    {mounted && createPortal(<><dialog ref={dialog} className={styles.editorDialog} aria-labelledby={title} onCancel={(event) => { event.preventDefault(); close(); }}>
      <header className={styles.editorHeader}><h2 id={title}>NOHARM Rubric Editor</h2><button className={styles.help} type="button" onClick={close}>Close Editor</button></header>
      <div className={styles.editorBody}><RubricEditorHost value={reportEditor}>{editorMounted && children}</RubricEditorHost></div>
    </dialog><dialog ref={confirmation} className={guardStyles.confirm} aria-labelledby={confirmTitle} aria-describedby={confirmDescription} onCancel={(event) => { event.preventDefault(); keepEditing(); }}>
      <h2 id={confirmTitle}>Unsaved rubric edits</h2>
      <p id={confirmDescription}>Save your reviewer copy before continuing, or discard these edits. Saving does not establish clinical validation.</p>
      {status.error && <p role="alert" className={guardStyles.error}>{status.error} Keep editing to review the rubric, or try saving again.</p>}
      {!status.canSave && !status.saving && status.dirty && <p>Save is unavailable in this editor. Keep editing to review the rubric and its notices, or discard these edits.</p>}
      <div className={guardStyles.actions}>
        <button autoFocus type="button" onClick={keepEditing}>Keep editing</button>
        <button type="button" disabled={status.saving || savePending} onClick={() => pending.current?.()}>Discard edits</button>
        <button className={guardStyles.save} type="button" disabled={status.saving || savePending || (status.dirty && !status.canSave)} onClick={() => { void saveAndContinue(); }}>{status.saving || savePending ? "Saving..." : status.dirty ? "Save and continue" : "Continue"}</button>
      </div>
    </dialog></>, document.body)}
  </>;
}

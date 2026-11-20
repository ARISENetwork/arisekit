"use client";

import { useEffect, useId, useRef } from "react";
import styles from "./RemovalDialog.module.css";

export interface RemovalRequest {
  title: string;
  text: string;
  detail?: string;
  // The same confirmation serves other actions, such as opening the tutorial.
  confirmLabel?: string;
  onConfirm: () => void;
  focusAfterRemove: string;
}

export default function RemovalDialog({ request, open, onClose }: {
  request: RemovalRequest;
  open: boolean;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const element = dialog.current!;
    if (!open) {
      element.close();
      return;
    }
    const overflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    cancel.current?.focus({ preventScroll: true });
    return () => { document.body.style.overflow = overflow; };
  }, [open]);

  const confirm = (): void => {
    dialog.current!.close();
    onClose();
    request.onConfirm();
    requestAnimationFrame(() => document.querySelector<HTMLElement>(request.focusAfterRemove)?.focus({ preventScroll: true }));
  };

  return (
    <dialog
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      className={styles.dialog}
      ref={dialog}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
      }}
    >
      <h2 id={titleId}>{request.title}</h2>
      <div id={descriptionId}>
        <p className={styles.item}>{request.text}</p>
        {request.detail && <p className={styles.detail}>{request.detail}</p>}
      </div>
      <div className={styles.actions}>
        <button ref={cancel} type="button" onClick={onClose}>Cancel</button>
        <button className={styles.remove} type="button" onClick={confirm}>{request.confirmLabel ?? "Remove"}</button>
      </div>
    </dialog>
  );
}

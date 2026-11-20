import { useEffect, useId, useRef, useState, type ReactElement } from "react";
import { useRouter } from "next/navigation";
import ApiModelSetup from "./ApiModelSetup";
import type { ModelSetupData } from "@/lib/api-model-setup";
import { noharmHref } from "@/lib/noharm-path";
import setupStyles from "./ApiModelSetup.module.css";
import styles from "./ModelSetupPopup.module.css";

// Model setup over the current page. Each opening loads the saved setup afresh, so closing discards unsaved choices.
export default function ModelSetupPopup({ open, onClose }: { open: boolean; onClose: () => void }): ReactElement {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [data, setData] = useState<ModelSetupData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(0);

  useEffect(() => {
    if (!open) { dialog.current?.close(); return; }
    dialog.current?.showModal();
    setOpening(current => current + 1);
    setData(null);
    setError(null);
    const controller = new AbortController();
    fetch("/api/pipeline/config", { cache: "no-store", signal: controller.signal })
      .then(async response => {
        const body = await response.json() as ModelSetupData & { error?: string };
        if (!response.ok) throw new Error(body.error ?? `Model setup returned HTTP ${response.status}.`);
        setData(body);
      })
      .catch((caught: Error) => { if (!controller.signal.aborted) setError(caught.message); });
    return () => controller.abort();
  }, [open]);

  const saved = (href: string | undefined, newRun: boolean): void => {
    // A new run is another project, so its setup continues there; a plain save stays on this page.
    if (newRun) { window.location.assign(href ?? noharmHref("/dataset")); return; }
    onClose();
    router.refresh();
  };

  const heading = <div className={setupStyles.popupHeading}><h2 id={titleId}>API model setup</h2><button type="button" className={setupStyles.close} aria-label="Close model setup" onClick={onClose}><svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m4 4 8 8M12 4l-8 8" /></svg></button></div>;
  return <dialog ref={dialog} className={styles.dialog} aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onClose(); }}>
    {data
      ? <ApiModelSetup key={opening} project={data.project} models={data.models} initialConfig={data.config} catalogError={data.catalogError} editable={data.editable} popup={{ titleId, onClose, onSaved: saved }} />
      : <div className={styles.waiting}>{heading}{error ? <p className={setupStyles.error} role="alert">{error}</p> : <p role="status">Loading model setup…</p>}</div>}
  </dialog>;
}

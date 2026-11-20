"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import type { ReviewImportPlan } from "@/lib/caseset/portable-review";
import { parsePortableReviewFile } from "@/lib/portable-html";
import styles from "./ExpertReviewFiles.module.css";

// Offline expert review, opened from the Rubrics page header: export an editor file for this case or the whole
// project, and import the files clinicians send back.
export default function ExpertReviewFiles({ project, caseId, version }: { project: string; caseId: string; version: string }): ReactNode {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const fileId = useId();
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  const [reviews, setReviews] = useState<unknown[]>([]);
  const [plan, setPlan] = useState<ReviewImportPlan[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const endpoint = "/api/runs/expert-review";
  const request = async (values: unknown[], preview: boolean): Promise<ReviewImportPlan[]> => {
    const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project, reviews: values, preview }) });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    return body.results as ReviewImportPlan[];
  };
  const load = async (files: FileList): Promise<void> => {
    setBusy(true); setReviews([]); setPlan([]); setMessage("");
    try {
      const values = await Promise.all(Array.from(files, async (file) => parsePortableReviewFile(await file.text())));
      const results = await request(values, true);
      setReviews(values); setPlan(results);
    } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  };
  const importReviews = async (): Promise<void> => {
    setBusy(true); setMessage("");
    try {
      const results = await request(reviews, false);
      setMessage(`${results.length} expert ${results.length === 1 ? "copy" : "copies"} imported. Original submissions retained; no copies were overwritten.`);
      setReviews([]); setPlan([]); router.refresh();
    } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  };
  const download = async (scope: "case" | "project"): Promise<void> => {
    setBusy(true); setMessage("");
    try {
      const query = new URLSearchParams({ project, caseId, version, scope });
      const response = await fetch(`${endpoint}?${query}`);
      if (!response.ok) throw new Error((await response.json()).error);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${scope === "project" ? project : caseId}.${version}.expert-review.html`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage("HTML downloaded. Send this file to each expert; they return their downloaded review HTML.");
    } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  };
  const button = "shrink-0 rounded-md border border-mc-line-strong bg-mc-surface px-3 py-1.5 text-sm font-medium transition-colors hover:bg-mc-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent disabled:opacity-50 motion-reduce:transition-none";
  const row = "flex items-center justify-between gap-4 border-t border-mc-line py-3 first:border-t-0";
  const ready = plan.filter((item) => item.status === "ready").length;
  return <>
    <button className={`${button} border-mc-accent text-mc-accent`} type="button" aria-haspopup="dialog" onClick={() => setOpen(true)}>Expert review</button>
    <dialog ref={dialog} aria-labelledby={titleId} className={styles.dialog} onCancel={(event) => { event.preventDefault(); if (!busy) setOpen(false); }}>
      <div className="flex items-start justify-between gap-4">
        <h2 className="m-0 text-lg font-semibold" id={titleId}>Expert review</h2>
        <button className={button} type="button" disabled={busy} onClick={() => setOpen(false)}>Close</button>
      </div>
      <p className="m-0 mt-1 text-sm text-mc-muted">Send a clinician an offline editor file. They return one HTML file with their independent copies.</p>
      <div className="mt-3">
        <div className={row}><div><strong className="block text-sm">This case</strong><span className="text-xs text-mc-muted">{caseId}, {version}</span></div><button className={button} disabled={busy} type="button" onClick={() => { void download("case"); }}>Export</button></div>
        <div className={row}><div><strong className="block text-sm">Whole project</strong><span className="text-xs text-mc-muted">{version} for every case; every rubric must pass validation</span></div><button className={button} disabled={busy} type="button" onClick={() => { void download("project"); }}>Export</button></div>
        <div className={row}><div><strong className="block text-sm">Returned reviews</strong><span className="text-xs text-mc-muted">Import the HTML files clinicians send back</span></div>
          <label className={`${button} cursor-pointer`} htmlFor={fileId}>Choose files</label>
          <input className="sr-only" id={fileId} type="file" accept=".html,text/html,.json,application/json" multiple disabled={busy} onChange={(event) => { if (event.target.files?.length) void load(event.target.files); event.target.value = ""; }} />
        </div>
      </div>
      {plan.length > 0 && <div className="mt-2 space-y-2">
        <ul className="m-0 list-disc pl-5 text-sm">{plan.map((item) => <li key={`${item.caseId}/${item.reviewer}`}>{item.caseId}: {item.version}, {item.status}</li>)}</ul>
        <button className={button} disabled={busy || ready === 0} type="button" onClick={() => { void importReviews(); }}>Import {ready} Expert {ready === 1 ? "Copy" : "Copies"}</button>
      </div>}
      <p className="m-0 mt-2 min-h-5 text-sm" role="status">{message}</p>
    </dialog>
  </>;
}

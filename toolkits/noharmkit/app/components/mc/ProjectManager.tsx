"use client";

import { useEffect, useId, useMemo, useRef, useState, type ReactElement } from "react";
import { useRouter } from "next/navigation";
import ImportProject from "@/components/ImportProject";
import type { ProjectRow } from "@/lib/project-manage";
import { NOTE_LIMIT, TITLE_LIMIT } from "@/lib/project-manage-limits";
import { noharmHref } from "@/lib/noharm-path";
import styles from "./ProjectManager.module.css";

async function send(method: "PATCH" | "DELETE", body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch("/api/projects", { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const result = await response.json() as Record<string, unknown> & { error?: string };
  if (!response.ok) throw new Error(result.error ?? `Projects returned HTTP ${response.status}.`);
  return result;
}

// Click the note to edit it in place; Enter or leaving the field saves, Escape cancels.
function NoteCell({ row, onSaved, onError }: { row: ProjectRow; onSaved: (note: string) => void; onError: (message: string) => void }): ReactElement {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(row.note);
  const [saving, setSaving] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) input.current?.focus(); }, [editing]);
  const save = async (): Promise<void> => {
    setEditing(false);
    if (draft.trim() === row.note) { setDraft(row.note); return; }
    setSaving(true);
    try { onSaved(String((await send("PATCH", { name: row.name, note: draft })).note ?? "")); }
    catch (caught) { setDraft(row.note); onError((caught as Error).message); }
    finally { setSaving(false); }
  };
  if (editing) return <input ref={input} className={styles.noteInput} aria-label={`Note for ${row.name}`} maxLength={NOTE_LIMIT} value={draft}
    onChange={event => setDraft(event.target.value)} onBlur={() => void save()}
    onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); input.current?.blur(); } if (event.key === "Escape") { event.preventDefault(); setDraft(row.note); setEditing(false); } }} />;
  return <button type="button" className={styles.note} data-empty={!row.note || undefined} disabled={saving} aria-label={row.note ? `Edit note for ${row.name}: ${row.note}` : `Add a note for ${row.name}`} onClick={() => { setDraft(row.note); setEditing(true); }}>
    {saving ? "Saving…" : row.note || "Add a note"}
  </button>;
}

// The display name edits in place after Rename; the folder name stays underneath, since records keep it.
function NameCell({ row, current, editing, onDone, onSaved, onError }: { row: ProjectRow; current: boolean; editing: boolean; onDone: () => void; onSaved: (title: string) => void; onError: (message: string) => void }): ReactElement {
  const [draft, setDraft] = useState(row.title || row.name);
  const [saving, setSaving] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) { setDraft(row.title || row.name); input.current?.select(); } }, [editing, row.name, row.title]);
  const save = async (): Promise<void> => {
    onDone();
    if (draft.trim() === (row.title || row.name)) return;
    setSaving(true);
    try { onSaved(String((await send("PATCH", { name: row.name, title: draft })).title ?? "")); }
    catch (caught) { onError((caught as Error).message); }
    finally { setSaving(false); }
  };
  return <>
    {editing
      ? <input ref={input} className={styles.nameInput} aria-label={`Display name for ${row.name}`} maxLength={TITLE_LIMIT} value={draft}
        onChange={event => setDraft(event.target.value)} onBlur={() => void save()}
        onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); input.current?.blur(); } if (event.key === "Escape") { event.preventDefault(); setDraft(row.title || row.name); onDone(); } }} />
      : <span className={styles.name}>{saving ? "Saving…" : row.title || row.name}</span>}
    {current && !editing && <span className={styles.current}>Current</span>}
    {row.title && <span className={styles.folder}>{row.name}</span>}
  </>;
}

export default function ProjectManager({ rows: initialRows, current }: { rows: ProjectRow[]; current: string }): ReactElement {
  const router = useRouter();
  const [rows, setRows] = useState(initialRows);
  const [search, setSearch] = useState("");
  const [pending, setPending] = useState<ProjectRow | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [status, setStatus] = useState<{ text: string; error?: boolean } | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const searchId = useId();
  useEffect(() => { setRows(initialRows); }, [initialRows]);
  useEffect(() => { if (pending) dialog.current?.showModal(); else dialog.current?.close(); }, [pending]);
  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return term ? rows.filter(row => `${row.name} ${row.title} ${row.note}`.toLowerCase().includes(term)) : rows;
  }, [rows, search]);

  const remove = async (): Promise<void> => {
    if (!pending) return;
    setDeleting(true);
    try {
      const result = await send("DELETE", { name: pending.name });
      setRows(current => current.filter(row => row.name !== pending.name));
      const label = pending.title || pending.name;
      setStatus({ text: typeof result.movedTo === "string" ? `Deleted ${label}. Its files are in projects/${result.movedTo}.` : `Deleted ${label}.` });
      setPending(null);
      router.refresh();
    } catch (caught) { setStatus({ text: (caught as Error).message, error: true }); setPending(null); }
    finally { setDeleting(false); }
  };

  return <div className={styles.page}>
    <header className={styles.header}>
      <div><h1>Projects</h1><p>Open, rename, annotate, or delete the projects in this workspace.</p></div>
      <div className={styles.search}><label htmlFor={searchId}>Search projects</label><input id={searchId} type="search" placeholder="Name or note" value={search} onChange={event => setSearch(event.target.value)} /></div>
    </header>
    <p className={styles.status} role="status" data-error={status?.error || undefined}>{status?.text ?? ""}</p>
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th scope="col">Project</th><th scope="col">Mode</th><th scope="col">Last updated</th><th scope="col">Note</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {visible.map(row => <tr key={row.name}>
            <th scope="row" className={styles.nameCell}><NameCell row={row} current={row.name === current} editing={renaming === row.name} onDone={() => setRenaming(null)} onSaved={title => { setRows(items => items.map(item => item.name === row.name ? { ...item, title } : item)); router.refresh(); }} onError={text => setStatus({ text, error: true })} /></th>
            <td><span className={styles.mode}>{row.mode === "api" ? "API" : "Local"}</span></td>
            <td className={styles.date}>{row.updatedAt?.slice(0, 10) ?? "Not run yet"}</td>
            <td className={styles.noteCell}><NoteCell row={row} onSaved={note => setRows(current => current.map(item => item.name === row.name ? { ...item, note } : item))} onError={text => setStatus({ text, error: true })} /></td>
            <td className={styles.actions}>
              <form action="/api/benchmark" method="post"><input type="hidden" name="benchmark" value={row.name} /><input type="hidden" name="returnTo" value={noharmHref("/dashboard")} /><button type="submit" className={styles.open}>Open</button></form>
              <button type="button" className={styles.rename} disabled={row.name === "demo"} title={row.name === "demo" ? "The bundled demo keeps its name." : undefined} aria-label={`Rename ${row.title || row.name}`} onClick={() => setRenaming(row.name)}>Rename</button>
              <button type="button" className={styles.delete} data-project={row.name} disabled={Boolean(row.locked)} title={row.locked ?? undefined} aria-label={`Delete ${row.name}`} onClick={() => setPending(row)}>Delete</button>
            </td>
          </tr>)}
          {!visible.length && <tr><td colSpan={5} className={styles.empty}>{rows.length ? "No projects match this search." : "No projects yet."}</td></tr>}
        </tbody>
      </table>
    </div>
    <ImportProject />
    <dialog ref={dialog} className={styles.dialog} aria-labelledby={titleId} onCancel={event => { event.preventDefault(); if (!deleting) setPending(null); }}>
      <h2 id={titleId}>Delete {pending?.title || pending?.name}?</h2>
      <p>Its files move to the projects/.deleted folder. Move the folder back to restore the project.</p>
      {pending?.name === current && <p>This is the current project; another one will open in its place.</p>}
      <div className={styles.dialogActions}>
        <button type="button" disabled={deleting} onClick={() => setPending(null)}>Cancel</button>
        <button type="button" className={styles.confirmDelete} disabled={deleting} onClick={() => void remove()}>{deleting ? "Deleting…" : "Delete project"}</button>
      </div>
    </dialog>
  </div>;
}

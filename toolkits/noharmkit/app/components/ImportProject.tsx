"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import styles from "./ImportProject.module.css";

export default function ImportProject() {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const router = useRouter();
  async function upload() {
    setBusy(true); setError(""); setNotice("");
    try {
      const name = files[0]?.webkitRelativePath.split("/")[0];
      if (!name) throw new Error("Choose a NOHARMKit project folder.");
      if (files.some(file => file.webkitRelativePath.split("/")[0] !== name)) throw new Error("Choose one project folder at a time.");
      // Hidden and dependency folders are never uploaded, so they do not count toward the limit.
      const kept = files.filter(file => !file.webkitRelativePath.split("/").some(part => part.startsWith(".") || ["node_modules", "venv", "__pycache__"].includes(part)));
      if (kept.reduce((sum, file) => sum + file.size, 0) > 12 * 1024 * 1024) throw new Error("Choose a project folder smaller than 12 MiB.");
      const packed: Record<string, string> = {};
      for (const file of kept) {
        const parts = file.webkitRelativePath.split("/");
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = "";
        for (let index = 0; index < bytes.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
        packed[parts.slice(1).join("/")] = btoa(binary);
      }
      const response = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, files: packed }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The project import was not confirmed. Try again.");
      setNotice(`Imported ${result.project}. Its saved cases, rubrics, responses, and results are now available.`);
      setFiles([]); if (input.current) input.current.value = "";
      router.refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The project could not be imported."); }
    finally { setBusy(false); }
  }
  return <details className={styles.import}>
    <summary>Import a project from your computer</summary>
    <p>Choose the NOHARMKit project folder created by your coding agent. Include its provenance.json, cases, rubrics, responses, and results. Import creates a separate project and preserves the original files.</p>
    <label>Project folder<input ref={input} type="file" {...{ webkitdirectory: "", directory: "" }} multiple disabled={busy} onChange={event => { setFiles(Array.from(event.target.files ?? [])); setError(""); setNotice(""); }} /></label>
    <button type="button" disabled={!files.length || busy} onClick={() => void upload()}>{busy ? "Saving project…" : "Import project"}</button>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </details>;
}

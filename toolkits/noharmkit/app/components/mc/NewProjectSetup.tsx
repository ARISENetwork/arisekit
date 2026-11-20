"use client";

import { useState } from "react";
import ProjectModeField from "./ProjectModeField";
import type { ProjectExecutionMode } from "@/lib/project-mode";
import styles from "./WelcomeWorkspace.module.css";

export default function NewProjectSetup({ projects, onCancel, onCreatingChange }: { projects: string[]; onCancel: () => void; onCreatingChange: (creating: boolean) => void }) {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executionMode, setExecutionMode] = useState<ProjectExecutionMode>("api");
  const duplicate = projects.includes(name);
  const create = async (): Promise<void> => {
    if (creating || duplicate) return;
    setCreating(true); onCreatingChange(true); setError(null);
    try {
      const response = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, idea: "", execution_mode: executionMode }) });
      const result = await response.json() as { href: string; error?: string };
      if (!response.ok) throw new Error(result.error);
      window.location.assign(result.href);
    } catch (caught) { setError((caught as Error).message); setCreating(false); onCreatingChange(false); }
  };
  return <form className={styles.newProjectForm} onSubmit={(event) => { event.preventDefault(); void create(); }}>
      <fieldset disabled={creating}>
        <label htmlFor="new-project-name">Project name</label>
        <input autoFocus aria-describedby="new-project-name-help" className={styles.projectField} id="new-project-name" maxLength={64} onChange={(event) => setName(event.target.value)} pattern="[a-z0-9]([a-z0-9]|-){0,63}" placeholder="vascular-surgery" required value={name} />
        <p className={styles.fieldHelp} id="new-project-name-help">Lowercase letters, numbers, and hyphens.</p>
      </fieldset>
      <ProjectModeField id="new-project-mode" value={executionMode} onChange={setExecutionMode} disabled={creating} />
      {duplicate && <p className={styles.formError} role="alert">This project already exists. Choose another name or resume it.</p>}
      <div className={styles.projectDialogActions}><button className={styles.dialogCancel} disabled={creating} type="button" onClick={onCancel}>Cancel</button><button className={styles.primaryAction} disabled={creating || duplicate} type="submit">{creating ? "Creating…" : "Create Project"}</button></div>
      {error && <p className={styles.formError} role="alert">{error}</p>}
    </form>;
}

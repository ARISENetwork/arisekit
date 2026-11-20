"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";

import Link from "@/components/MotionLink";
import Dropdown from "@/components/Dropdown";
import NewProjectSetup from "@/components/mc/NewProjectSetup";
import ProjectModeField from "@/components/mc/ProjectModeField";
import type { ProjectExecutionMode } from "@/lib/project-mode";
import { resumableProjects, welcomeMode } from "@/lib/onboarding";
import type { WelcomeMode } from "@/lib/onboarding";
import { noharmHref } from "@/lib/noharm-path";

import styles from "./WelcomeWorkspace.module.css";

export default function WelcomeContent({ benchmark, projects, exampleProject, mode: initialMode, projectModes, projectTitles = {} }: { benchmark: string; projects: string[]; exampleProject?: string; mode: WelcomeMode; projectModes: Record<string, ProjectExecutionMode>; projectTitles?: Record<string, string> }) {
  const query = useSearchParams();
  const [modeChoices, setModeChoices] = useState(() => new Map<string, ProjectExecutionMode>());
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const walkthroughComplete = query?.get("walkthrough") === "complete";
  const requestedMode = query ? welcomeMode(projects, exampleProject, query.get("mode")) : initialMode;
  const [mode, setMode] = useState(requestedMode);
  const [creating, setCreating] = useState(false);
  const newDialog = useRef<HTMLDialogElement>(null);
  const resumeDialog = useRef<HTMLDialogElement>(null);
  const names = resumableProjects(projects, exampleProject);
  const [selected, setSelected] = useState(names.includes(benchmark) ? benchmark : names[0] ?? "");
  const executionMode = modeChoices.get(selected) ?? (Object.hasOwn(projectModes, selected) ? projectModes[selected] : "api");
  useEffect(() => { setMode(requestedMode); }, [requestedMode]);
  useEffect(() => {
    if (mode === "new") newDialog.current?.showModal();
    else newDialog.current?.close();
    if (mode === "resume") resumeDialog.current?.showModal();
    else resumeDialog.current?.close();
    setResumeError(null);
  }, [mode]);
  const close = (): void => {
    if (creating || resuming) return;
    setMode("entry");
    const url = new URL(window.location.href);
    if (url.searchParams.has("mode")) {
      url.searchParams.delete("mode");
      window.history.replaceState(null, "", url);
    }
  };
  const resume = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (resuming) return;
    const form = new FormData(event.currentTarget);
    setResuming(true); setResumeError(null);
    try {
      const response = await fetch("/api/benchmark", { method: "POST", headers: { Accept: "application/json" }, body: form });
      const result = await response.json() as { href: string; error?: string };
      if (!response.ok) throw new Error(result.error);
      window.location.assign(result.href);
    } catch (caught) { setResumeError((caught as Error).message); setResuming(false); }
  };
  const returning = names.length > 0;
  const openNew = (): void => setMode("new");
  const createButton = (primary: boolean) => <button className={primary ? styles.heroPrimary : styles.heroSecondary} type="button" aria-haspopup="dialog" onClick={openNew}>Create project</button>;
  return <><div className={styles.welcomeLayout} data-entry="true" data-returning={returning}>
    <section aria-label="Get started" className={`${styles.stage} ${styles.hero}`}>
      <h1>{returning ? "Welcome back to " : "Welcome to "}NOHARM<span className={styles.kit}>Kit</span></h1>
      <p className={styles.heroLead}>{returning
        ? "Continue a saved benchmark, or start a new one with your own cases."
        : walkthroughComplete
          ? "You have finished the walkthrough. Create a project to build a benchmark from your own cases."
          : "Build a benchmark that scores clinical recommendations by their potential to harm patients. The guided walkthrough takes you through every step on a prepared UTI example."}</p>
      <div className={styles.heroActions}>
        {returning
          ? <><button className={styles.heroPrimary} type="button" aria-haspopup="dialog" onClick={() => setMode("resume")}>Resume project</button>{createButton(false)}<Link className={styles.heroLink} href={noharmHref("/projects")}>Manage projects</Link></>
          : walkthroughComplete
            ? <>{createButton(true)}<Link className={styles.heroSecondary} href={noharmHref("/tutorial")}>Replay walkthrough</Link></>
            : <><Link className={styles.heroPrimary} data-recommended="true" href={noharmHref("/tutorial")}>Start walkthrough</Link>{createButton(false)}</>}
      </div>
    </section>
    <section aria-label="Learn NOHARMKit" className={styles.stage}>
      <h2>Learn NOHARM<span className={styles.kit}>Kit</span></h2>
      <ul className={styles.resources}>
        {returning && <li><Link className={styles.resource} href={noharmHref("/tutorial")}><span><strong>Guided walkthrough</strong><span>Build a benchmark from a prepared UTI example, step by step.</span></span><span className={styles.resourceAction}>Replay walkthrough</span></Link></li>}
        <li><Link className={styles.resource} href={noharmHref("/rubric-tutorial")}><span><strong>Rubric editor tutorial</strong><span>Learn the rubric editor on an example case, one control at a time.</span></span><span className={styles.resourceAction}>Open tutorial</span></Link></li>
        <li><Link className={styles.resource} href={noharmHref("/guide")}><span><strong>Quick reference</strong><span>How to build and review a benchmark, step by step.</span></span><span className={styles.resourceAction}>Read reference</span></Link></li>
        <li><Link className={styles.resource} href={noharmHref("/framework")}><span><strong>Scoring framework</strong><span>The rubric structure, harm ratings, and scoring approach.</span></span><span className={styles.resourceAction}>Review scoring framework</span></Link></li>
      </ul>
    </section>
  </div>
    <dialog ref={newDialog} className={styles.projectDialog} aria-labelledby="new-project-title" onCancel={(event) => { event.preventDefault(); close(); }}>
      <header className={styles.projectDialogHeader}>
        <h2 id="new-project-title">New project</h2>
        <button className={styles.projectDialogClose} type="button" aria-label="Close new project" disabled={creating} onClick={close}><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="m6 6 12 12M18 6 6 18" /></svg></button>
      </header>
      <NewProjectSetup projects={projects} onCancel={close} onCreatingChange={setCreating} />
    </dialog>
    <dialog ref={resumeDialog} className={styles.projectDialog} aria-labelledby="resume-project-title" onCancel={(event) => { event.preventDefault(); close(); }}>
      <header className={styles.projectDialogHeader}>
        <h2 id="resume-project-title">Resume project</h2>
        <button className={styles.projectDialogClose} type="button" aria-label="Close resume project" disabled={resuming} onClick={close}><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="m6 6 12 12M18 6 6 18" /></svg></button>
      </header>
      {names.length ? <form className={styles.resumeForm} action="/api/benchmark" method="post" onSubmit={(event) => { void resume(event); }}>
        <label htmlFor="resume-project">Project</label>
        <Dropdown autoFocus id="resume-project" name="benchmark" className={styles.projectField} disabled={resuming} value={selected} onChange={(event) => { setSelected(event.target.value); setResumeError(null); }}>{names.map((name) => <option key={name} value={name}>{projectTitles[name] ?? name}</option>)}</Dropdown>
        <input name="returnTo" type="hidden" value={noharmHref("/dashboard")} />
        <ProjectModeField id="resume-project-mode" value={executionMode} onChange={(value) => setModeChoices(choices => new Map(choices).set(selected, value))} disabled={resuming} />
        <div className={styles.projectDialogActions}><button className={styles.dialogCancel} type="button" disabled={resuming} onClick={close}>Cancel</button><button className={styles.primaryAction} type="submit" disabled={resuming}>{resuming ? "Resuming…" : "Resume project"}</button></div>
        {resumeError && <p className={styles.formError} role="alert">{resumeError}</p>}
      </form> : <><p className={styles.lead}>There are no saved projects to resume yet.</p><div className={styles.projectDialogActions}><button className={styles.dialogCancel} type="button" onClick={close}>Close</button></div></>}
    </dialog>
  </>;
}

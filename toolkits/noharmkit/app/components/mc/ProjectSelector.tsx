"use client";

import { usePathname } from "next/navigation";

import Dropdown from "@/components/Dropdown";
import ShellLink from "@/components/mc/ShellLink";
import { BUTTON } from "@/components/mc/ui";
import type { NavData } from "@/components/mc/nav";
import { localPath, noharmHref } from "@/lib/noharm-path";

export default function ProjectSelector({ nav, placement, onNewProject }: { nav: NavData; placement: "sidebar" | "topbar"; onNewProject?: () => void }) {
  const pathname = usePathname();
  const sidebar = placement === "sidebar";
  const id = `mc-project-${placement}`;
  return (
    <div className={sidebar ? "flex flex-col gap-1" : "flex min-w-0 items-center gap-2"}>
      <form action="/api/benchmark" className={sidebar ? "flex min-w-0 flex-col gap-1.5" : "flex min-w-0 flex-1"} method="post">
        <label className={sidebar ? "px-2.5 text-xs font-medium text-mc-faint" : "sr-only"} htmlFor={id}>Project</label>
        <input name="returnTo" type="hidden" value={pathname} />
        <Dropdown
          className="h-8 w-full min-w-0 truncate rounded-md border border-mc-line-strong bg-mc-surface px-2.5 text-[13.5px]! font-medium! leading-5! text-mc-ink transition-colors hover:border-mc-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent"
          id={id}
          disabled={nav.benchmarks.length === 0}
          name="benchmark"
          onChange={(event) => event.currentTarget.form?.requestSubmit()}
          title={nav.titles?.[nav.benchmark] ? `${nav.titles[nav.benchmark]} (${nav.benchmark})` : nav.benchmark}
          value={nav.benchmark}
        >
          {nav.benchmarks.length === 0 && <option value="">No projects yet</option>}
          {nav.benchmarks.map((name) => <option key={name} value={name}>{nav.titles?.[name] ?? name}</option>)}
        </Dropdown>
      </form>
      {onNewProject ? <button className={`${BUTTON} shrink-0 whitespace-nowrap`} onClick={onNewProject} type="button">New Project</button> : <ShellLink className={sidebar ? "grid grid-cols-[22px_minmax(0,1fr)] items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13.5px] font-medium text-mc-muted no-underline transition-colors hover:bg-mc-surface/60 hover:text-mc-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent" : `${BUTTON} shrink-0 whitespace-nowrap`} hard={localPath(pathname) === "/review"} href={noharmHref("/welcome#new-project")}>
        {sidebar && <svg aria-hidden="true" className="mx-auto h-3.5 w-3.5" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth={1.6} viewBox="0 0 14 14"><path d="M7 2.5v9M2.5 7h9" /></svg>}
        <span>New Project</span>
      </ShellLink>}
      {nav.benchmark && <a className={sidebar ? "rounded-md px-2.5 py-[7px] text-[13px] font-medium text-mc-muted underline-offset-4 transition-colors hover:bg-mc-surface/60 hover:text-mc-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent" : `${BUTTON} shrink-0`} href={`/api/projects/export?project=${encodeURIComponent(nav.benchmark)}`} download title="Download project inputs, rubrics, responses, judgments, scores, configuration, and provenance as a tar.gz archive">Download project</a>}
    </div>
  );
}

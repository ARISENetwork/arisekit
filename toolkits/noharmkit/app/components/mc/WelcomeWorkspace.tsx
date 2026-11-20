"use client";


import { createContext, useCallback, useContext, useEffect, useRef, useState, useTransition } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useMotionNavigation } from "@/components/NavigationMotion";

import ProjectSelector from "@/components/mc/ProjectSelector";
import Roadmap from "@/components/mc/Roadmap";
import ShellLink from "@/components/mc/ShellLink";
import { ModelSetupLink, useApiExecution } from "@/components/mc/ApiExecution";
import ThemeToggle from "@/components/mc/ThemeToggle";
import type { NavData } from "@/components/mc/nav";
import { noharmHref } from "@/lib/noharm-path";
import { STEP_KEYS, type StepKey } from "@/lib/caseset/steps";
import { isTutorialProject } from "@/lib/onboarding";

import styles from "./WelcomeWorkspace.module.css";

const WelcomeContext = createContext({ registerBeforeRefresh: (_save: () => Promise<boolean>): (() => void) => () => {} });
export const useWelcomeWorkspace = () => useContext(WelcomeContext);

export default function WelcomeWorkspace({ nav, children, tutorialStep, footer }: { nav: NavData; children: ReactNode; tutorialStep?: StepKey; footer?: ReactNode }) {
  const router = useRouter();
  const navigate = useMotionNavigation();
  const pathname = usePathname();
  const welcome = pathname === noharmHref("/welcome");
  const apiMode = useApiExecution()?.mode === "api";
  const beforeRefresh = useRef<(() => Promise<boolean>) | null>(null);
  const registerBeforeRefresh = useCallback((save: () => Promise<boolean>): (() => void) => {
    beforeRefresh.current = save;
    return () => { if (beforeRefresh.current === save) beforeRefresh.current = null; };
  }, []);
  const [refreshPending, startRefresh] = useTransition();
  const [savePending, setSavePending] = useState(false);
  const refreshing = refreshPending || savePending;
  const refresh = useCallback(async (): Promise<void> => {
    setSavePending(true);
    try {
      if (beforeRefresh.current && !await beforeRefresh.current()) return;
      startRefresh(() => router.refresh());
    } finally { setSavePending(false); }
  }, [router, startRefresh]);
  const startBenchmark = useCallback((): void => {
    navigate(`${noharmHref("/welcome")}?mode=new`);
  }, [navigate]);
  useEffect(() => { if (welcome && window.location.hash === "#new-project") startBenchmark(); }, [welcome, startBenchmark]);
  return (
    <WelcomeContext.Provider value={{ registerBeforeRefresh }}>
      <div className={styles.workspace} data-mc data-welcome-workspace data-onboarding={welcome}>
        <div className={styles.persistent}>
          <header className={styles.header}>
            <nav aria-label="Breadcrumb" className={styles.breadcrumb}>
              <ol>
                <li><ShellLink className={styles.brand} hard href="/kits"><strong>ARISE</strong>Kit</ShellLink></li>
                <li>
                  <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m6 3 5 5-5 5" /></svg>
                  <ShellLink className={styles.brand} hard href={noharmHref("/welcome")} aria-current={welcome ? "page" : undefined}><strong>NOHARM</strong>Kit</ShellLink>
                </li>
              </ol>
            </nav>
            {/* The welcome page chooses a project in its own panel, so the bar carries no project there. */}
            <div className={styles.project}>{tutorialStep ? <strong className={styles.draftProject}>Tutorial draft</strong> : !welcome && <ProjectSelector nav={nav} onNewProject={startBenchmark} placement="topbar" />}</div>
            <nav aria-label="Workspace actions" className={styles.links}>
              <div className={styles.headerActions}>
                <button className={styles.refresh} type="button" aria-label="Refresh" title="Reload saved project data" disabled={refreshing} aria-busy={refreshing} onClick={() => void refresh()}>
                  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 17.9 17" /></svg>
                </button>
                <span className="sr-only" role="status">{refreshing ? "Refreshing saved project data…" : ""}</span>
                <ThemeToggle iconOnly />
              </div>
            </nav>
          </header>
        </div>
        <div className={styles.body}>
          <div className={styles.mainColumn}>
            {!welcome && <aside className={styles.pipelinePanel} aria-label="Pipeline sidebar">
              <nav className={styles.sidebarLinks} aria-label="Workspace navigation">
                <ShellLink hard={false} href={noharmHref("/dashboard")}><svg aria-hidden="true" className={styles.sidebarIcon} viewBox="0 0 24 24"><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="13" y="3" width="6" height="6" rx="1" /><rect x="3" y="13" width="6" height="6" rx="1" /><rect x="13" y="13" width="6" height="6" rx="1" /></svg>Dashboard</ShellLink>
                <ShellLink hard={false} href={noharmHref("/guide")}><svg aria-hidden="true" className={styles.sidebarIcon} viewBox="0 0 24 24"><path d="M3 4h7l2 2 2-2h7v15h-7l-2 2-2-2H3zM12 6v15" /></svg>Quick Reference</ShellLink>
                <ShellLink hard={false} href={noharmHref("/framework")}><svg aria-hidden="true" className={styles.sidebarIcon} viewBox="0 0 24 24"><rect x="3" y="3" width="16" height="16" rx="2" /><path d="M8 3v16M3 8h16M3 14h16" /></svg>Framework</ShellLink>
                {apiMode && <ModelSetupLink><svg aria-hidden="true" className={styles.sidebarIcon} viewBox="0 0 24 24"><path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1" /><circle cx="15" cy="6" r="2" /><circle cx="9" cy="12" r="2" /><circle cx="17" cy="18" r="2" /></svg>Model setup</ModelSetupLink>}
              </nav>
              <Roadmap exampleStep={tutorialStep ? STEP_KEYS.indexOf(tutorialStep) : null} hideContext={Boolean(tutorialStep)} nav={nav} tutorial={Boolean(tutorialStep) || isTutorialProject(nav.benchmark)} workspace />
            </aside>}
            <main className={styles.preview} data-pipeline={!welcome}>
              <div className={styles.workspaceContent}>{children}</div>
            </main>
            {footer}
          </div>
        </div>
      </div>
    </WelcomeContext.Provider>
  );
}

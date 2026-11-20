"use client";

import { usePathname, useSearchParams } from "next/navigation";

import ShellLink from "@/components/mc/ShellLink";
import { DOT_CLASS, DOT_LABEL } from "@/components/mc/nav";
import type { NavData } from "@/components/mc/nav";
import { navigationParams } from "@/lib/caseset/routes";
import { localPath } from "@/lib/noharm-path";
import { roadmapStops } from "@/lib/roadmap";
import styles from "./WelcomeWorkspace.module.css";

const WORKFLOW_HINTS: Record<string, string> = {
  cases: "Add your cases",
  rubrics: "Build your rubrics",
  responses: "Test your models",
  autograding: "Review judgments",
  scores: "Calculate scores",
  leaderboard: "Compare models",
};

export default function Roadmap({ nav, workspace = false, exampleStep = null, draft = false, tutorial = false, hideContext = false }: { nav: NavData; workspace?: boolean; exampleStep?: number | null; draft?: boolean; tutorial?: boolean; hideContext?: boolean }) {
  const local = localPath(usePathname()) ?? "/";
  const stops = roadmapStops(nav, local, navigationParams(useSearchParams()));
  const hard = local === "/review";
  if (workspace) return (
    <nav aria-label="Roadmap" className={styles.roadmap}>
      <div className={styles.roadmapHeading}><strong>Pipeline</strong>{!hideContext && (exampleStep !== null ? <span>Illustrative example</span> : tutorial && <span>Tutorial walkthrough</span>)}</div>
      <ol className={styles.stops}>
        {stops.filter((stop) => stop.key !== "welcome").map((stop, i) => {
          const current = exampleStep === null ? stop.current : exampleStep === i;
          const hint = WORKFLOW_HINTS[stop.key];
          const className = `${styles.stop} ${current ? styles.current : ""}`;
          const content = <><span aria-hidden="true" className={styles.stopNumber}>{i + 1}</span><span className={styles.stopLabel}><span>{stop.name}</span><span className={styles.stopHint}>{hint}</span></span></>;
          return <li key={stop.key}>{draft ? <span aria-current={current ? "step" : undefined} aria-disabled={!current} className={className} title={hint}>{content}</span> : <ShellLink aria-current={current ? "page" : undefined} className={className} hard={false} href={stop.href}>{content}</ShellLink>}</li>;
        })}
      </ol>
    </nav>
  );
  return (
    <nav aria-label="Roadmap" className="mx-auto mb-5 max-w-[1240px] px-4 min-[760px]:px-9">
      <ol className="m-0 flex list-none flex-wrap items-center gap-1.5 p-0">
        {stops.map((stop, i) => (
          <li className="flex items-center gap-1.5" key={stop.key}>
            {i > 0 && <span aria-hidden="true" className="h-px w-3 bg-mc-line-strong" />}
            <ShellLink aria-current={stop.current ? "page" : undefined} className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs no-underline transition-colors motion-reduce:transition-none ${stop.current ? "border-mc-accent bg-mc-accent-bg font-semibold text-mc-accent" : "border-mc-line bg-mc-surface text-mc-muted hover:text-mc-ink"}`} hard={hard} href={stop.href} title={DOT_LABEL[stop.dot]}>
              <span aria-hidden="true" className={`h-[7px] w-[7px] rounded-full ${DOT_CLASS[stop.dot]}`} />
              {stop.name}
            </ShellLink>
          </li>
        ))}
      </ol>
    </nav>
  );
}

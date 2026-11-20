import type { ReactNode } from "react";

import BenchmarkList from "@/components/mc/BenchmarkList";
import McShell from "@/components/mc/McShell";
import { getCurrent } from "@/lib/caseset/current";
import { projectsRoot } from "@/lib/caseset/paths";
import ApiExecutionProvider, { ApiRunPanel } from "@/components/mc/ApiExecution";
import { readProjectMode } from "@/lib/project-mode-store";
import { loadApiPipelineConfig } from "@/lib/api-pipeline-store";
import { isTutorialProject } from "@/lib/onboarding";

export const dynamic = "force-dynamic";

export default async function McLayout({ children }: { children: ReactNode }): Promise<ReactNode> {
  const current = await getCurrent();
  const root = projectsRoot();
  if (!current) return <BenchmarkList root={root} />;
  const demo = current.bench.name === "demo" && current.bench.cases.some(item => item.page.provenance.synthetic === true);
  const mode = demo || isTutorialProject(current.bench.name) ? "local" : readProjectMode(root, current.bench.name);
  // The run context wraps the shell, so the sidebar can open model setup; the run card sits above the page.
  return <ApiExecutionProvider key={current.bench.name} project={current.bench.name} mode={mode} configured={Boolean(loadApiPipelineConfig(root, current.bench.name))}><McShell current={current}><ApiRunPanel />{children}</McShell></ApiExecutionProvider>;
}

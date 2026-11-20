import WelcomeContent from "@/components/mc/WelcomeContent";
import type { Benchmark } from "@/lib/caseset/metrics";
import { welcomeMode } from "@/lib/onboarding";
import type { ProjectExecutionMode } from "@/lib/project-mode";

export default function Welcome({ bench, projects, mode, exampleProject, projectModes = {}, projectTitles = {} }: { bench: Benchmark; projects?: string[]; projectsRoot?: string; mode?: unknown; exampleProject?: string; projectModes?: Record<string, ProjectExecutionMode>; projectTitles?: Record<string, string> }) {
  const names = projects ?? (bench.name ? [bench.name] : []);
  const demo = bench.name === exampleProject && !bench.cases.every((item) => item.page.provenance.synthetic === true) ? undefined : exampleProject;
  const resolved = welcomeMode(names, demo, mode);
  return <WelcomeContent benchmark={bench.name} projects={names} exampleProject={demo} mode={resolved} projectModes={projectModes} projectTitles={projectTitles} key={bench.name} />;
}

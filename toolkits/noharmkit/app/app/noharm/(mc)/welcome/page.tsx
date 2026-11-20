import { redirect } from "next/navigation";

import Welcome from "@/components/mc/Welcome";
import { getCurrent } from "@/lib/caseset/current";
import { projectsRoot } from "@/lib/caseset/paths";
import { readProjectMode } from "@/lib/project-mode-store";

export const dynamic = "force-dynamic";

export default async function WelcomePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }): Promise<React.ReactNode> {
  const query = await searchParams;
  const requested = query.mode;
  if (query.review === "project-mode") redirect(`/noharm/welcome${requested === "new" || requested === "resume" ? `?mode=${requested}` : ""}`);
  if (requested === "tutorial") redirect("/noharm/tutorial");
  const current = await getCurrent();
  if (!current) return null;
  const exampleProject = current.names.find((name) => name.toLowerCase() === "demo");
  const root = projectsRoot();
  const projectModes = Object.fromEntries(current.names.map(name => [name, readProjectMode(root, name)]));
  return <Welcome bench={current.bench} projects={current.names} mode={requested} exampleProject={exampleProject} projectModes={projectModes} projectTitles={current.titles} />;
}

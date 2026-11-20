import type { ReactElement } from "react";
import ProjectManager from "@/components/mc/ProjectManager";
import { projectsRoot } from "@/lib/caseset/paths";
import { getCurrent } from "@/lib/caseset/current";
import { projectRows } from "@/lib/project-manage";

export const dynamic = "force-dynamic";
export const metadata = { title: "Projects | ARISEKit" };

export default async function ProjectsPage(): Promise<ReactElement | null> {
  const current = await getCurrent();
  if (!current) return null;
  const root = projectsRoot();
  return <ProjectManager rows={projectRows(root, current.names)} current={current.bench.name} />;
}

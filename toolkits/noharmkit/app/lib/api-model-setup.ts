import { projectsRoot } from "@/lib/caseset/paths";
import { loadApiPipelineConfig } from "@/lib/api-pipeline-store";
import type { ApiModelOption, ApiPipelineConfig } from "@/lib/api-pipeline-config";
import type { Current } from "@/lib/caseset/current";
import { isTutorialProject } from "@/lib/onboarding";
import { loadOpenRouterModels } from "@/lib/openrouter-models";
import { readProjectMode } from "@/lib/project-mode-store";

export interface ModelSetupData { project: string; config: ApiPipelineConfig | null; models: ApiModelOption[]; catalogError?: string; editable: boolean }

// What the model setup page and popup show for the current project.
export async function loadModelSetup(current: Current): Promise<ModelSetupData> {
  const root = projectsRoot();
  const project = current.bench.name;
  const prepared = isTutorialProject(project) || project === "demo" && current.bench.cases.some(item => item.page.provenance.synthetic === true);
  const editable = !prepared && readProjectMode(root, project) === "api";
  try {
    return { project, config: loadApiPipelineConfig(root, project), models: await loadOpenRouterModels(), editable };
  } catch (caught) {
    return { project, config: loadApiPipelineConfig(root, project), models: [], catalogError: (caught as Error).message, editable };
  }
}

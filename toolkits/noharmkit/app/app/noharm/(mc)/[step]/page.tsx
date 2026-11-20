import { projectsRoot } from "@/lib/caseset/paths";
import { notFound, redirect } from "next/navigation";
import type { ReactNode } from "react";

import PendingDataset from "@/components/mc/PendingDataset";
import DatasetWorkspace from "@/components/mc/DatasetWorkspace";
import { tutorialDataset } from "@/lib/uti-tutorial-benchmark";
import { datasetFields } from "@/lib/dataset-fields";
import { caseHasResults, datasetOutdated } from "@/lib/dataset-edit";
import { casesetDir, inside } from "@/lib/caseset/paths";
import { datasetSources } from "@/lib/dataset-sources";
import { readDatasetDrafts } from "@/lib/dataset-drafts";
import StageActions from "@/components/mc/StageActions";
import StepHeading from "@/components/mc/StepHeading";
import type { StepProps } from "@/components/mc/StepFrame";
import AutogradingStep from "@/components/mc/steps/AutogradingStep";
import CasesStep from "@/components/mc/steps/CasesStep";
import LeaderboardStep from "@/components/mc/steps/LeaderboardStep";
import ResponsesStep from "@/components/mc/steps/ResponsesStep";
import ApiResponseModels, { type ApiResponseSetup } from "@/components/mc/ApiResponseModels";
import RubricsStep from "@/components/mc/steps/RubricsStep";
import ScoresStep from "@/components/mc/steps/ScoresStep";
import { Card } from "@/components/mc/ui";
import { getCurrent } from "@/lib/caseset/current";
import { datasetRedirect, resolveStepParams } from "@/lib/caseset/routes";
import { stepForRoute } from "@/lib/caseset/steps";
import type { StepKey } from "@/lib/caseset/steps";
import { readProjectMode } from "@/lib/project-mode-store";
import { loadApiPipelineConfig } from "@/lib/api-pipeline-store";
import { initialModelTeams } from "@/lib/api-model-teams";
import { withApiResponseModels } from "@/lib/api-response-status";
import { loadPrompts, usedPromptIds } from "@/lib/response-prompts";
import { loadOpenRouterModels } from "@/lib/openrouter-models";
import { isTutorialProject } from "@/lib/onboarding";

export const dynamic = "force-dynamic";

const VIEWS: Partial<Record<StepKey, (props: StepProps) => ReactNode>> = {
  cases: CasesStep,
  rubrics: RubricsStep,
  responses: ResponsesStep,
  autograding: AutogradingStep,
  scores: ScoresStep,
};

interface StepPageProps {
  params: Promise<{ step: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function StepPage({ params, searchParams }: StepPageProps): Promise<ReactNode> {
  const { step: route } = await params;
  const step = stepForRoute(route);
  if (!step) notFound();
  if (route === "cases" || route === "inputs") redirect(datasetRedirect(await searchParams));
  const search = await searchParams;
  const current = await getCurrent();
  if (!current) notFound();
  let { bench } = current;
  const root = projectsRoot();
  let apiSetup: ApiResponseSetup | undefined;
  const prepared = isTutorialProject(bench.name) || bench.name === "demo" && bench.cases.some(item => item.page.provenance.synthetic === true);
  if (["responses", "autograding", "scores"].includes(step) && !prepared && readProjectMode(root, bench.name) === "api") {
    const config = loadApiPipelineConfig(root, bench.name);
    const team = config ? initialModelTeams(config).responses : null;
    if (team) bench = withApiResponseModels(bench, team);
    if (step === "responses") {
      apiSetup = { team, models: [], prompts: [] };
      try { apiSetup.prompts = loadPrompts(root, bench.name).map(({ id, name }) => ({ id, name })); }
      catch (caught) {
        apiSetup.promptsError = (caught as Error).message;
        apiSetup.promptsInUse = usedPromptIds(root, bench.name).size > 0;
      }
      if (team) {
        try { apiSetup.models = await loadOpenRouterModels(); }
        catch (caught) { apiSetup.catalogError = (caught as Error).message; }
      }
    }
  }
  const resolved = resolveStepParams(bench, search, step);
  if (route === "dataset") return <DatasetWorkspace example={tutorialDataset()} key={bench.name} project={bench.name} params={resolved} cases={bench.cases.map((c) => ({ ...datasetFields(c.page.source), id: c.caseId, hasRubric: c.page.tables.some((t) => t.status === "pass" && !t.outdated), hasResults: caseHasResults(casesetDir(root, bench.name), c.caseId), outdated: datasetOutdated(c.page) }))} sources={datasetSources(casesetDir(root, bench.name), bench.cases.map((c) => ({ id: c.caseId, source: c.page.source })))} />;
  if (step === "leaderboard") return <LeaderboardStep bench={bench} />;
  const View = VIEWS[step];
  if (!View) notFound();
  if (!resolved) {
    const projectDir = casesetDir(root, bench.name);
    return <><header className="mb-5 flex flex-wrap items-start gap-3.5"><StepHeading step={step} /></header>{apiSetup && <div className="mb-4"><ApiResponseModels bench={bench} {...apiSetup} /></div>}<Card className="p-5"><PendingDataset project={bench.name} drafts={readDatasetDrafts(root, bench.name)} draftPath={inside(projectDir, "drafts", "dataset.json")} sources={datasetSources(projectDir, [])} /></Card><StageActions step={step} project={bench.name} blocked="Import your dataset before running this stage." /></>;
  }
  if (step === "responses" && apiSetup) return <ResponsesStep bench={bench} params={resolved} apiSetup={apiSetup} />;
  return <View bench={bench} params={resolved} />;
}

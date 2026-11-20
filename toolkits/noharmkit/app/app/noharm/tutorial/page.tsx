import { Suspense, type ReactNode } from "react";
import AnswerTableEditor from "@/components/AnswerTableEditor";
import UtiTutorial from "@/components/mc/UtiTutorial";
import RubricsStep from "@/components/mc/steps/RubricsStep";
import ResponsesStep from "@/components/mc/steps/ResponsesStep";
import AutogradingStep from "@/components/mc/steps/AutogradingStep";
import ScoresStep from "@/components/mc/steps/ScoresStep";
import LeaderboardStep from "@/components/mc/steps/LeaderboardStep";
import type { NavData } from "@/components/mc/nav";
import { resolveStepParams } from "@/lib/caseset/routes";
import { STEP_KEYS, stepForRoute } from "@/lib/caseset/steps";
import { TUTORIAL_STAGES } from "@/lib/uti-tutorial";
import { tutorialBenchmark, tutorialDataset, TUTORIAL_PROJECT } from "@/lib/uti-tutorial-benchmark";
import { buildLeaderboard } from "@/lib/caseset/leaderboard";

export const metadata = { title: "Guided tutorial | ARISEKit" };

export default async function TutorialPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }): Promise<ReactNode> {
  const query = await searchParams;
  const editor = query.step === "review";
  const index = editor ? 1 : Math.max(0, TUTORIAL_STAGES.findIndex((stage) => stage.key === query.step));
  const bench = tutorialBenchmark();
  const params = resolveStepParams(bench, query, editor ? "rubrics" : stepForRoute(TUTORIAL_STAGES[index].key) ?? undefined)!;
  const nav: NavData = { benchmark: TUTORIAL_PROJECT, benchmarks: [], synthetic: true, dev: false, updatedLabel: null, dots: Object.fromEntries(STEP_KEYS.map((step) => [step, bench.steps[step].dot])) as NavData["dots"] };
  const views = [null, <RubricsStep key="rubrics" bench={bench} params={params} />, <ResponsesStep key="responses" bench={bench} params={params} />, <AutogradingStep key="autograding" bench={bench} params={params} />, <ScoresStep key="scores" bench={bench} params={params} />, <LeaderboardStep key="leaderboard" bench={bench} />];
  const exportRows = buildLeaderboard(bench).map((row) => ({ model: row.model, scored: row.scored, expected: row.expected, meanF1: row.f1, draft: row.draft, provisional: row.provisional }));
  return <Suspense><UtiTutorial example={tutorialDataset()} index={index} nav={nav} editor={editor} exportRows={exportRows} editorContent={<main className="bg-[hsl(var(--background))] text-[hsl(var(--foreground))] [color-scheme:light]"><AnswerTableEditor caseId={params.caseId} source={{ caseset: TUTORIAL_PROJECT, version: params.version! }} synthetic /></main>}>{views[index]}</UtiTutorial></Suspense>;
}

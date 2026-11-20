import Link from "@/components/MotionLink";

import { ApiStageAction } from "@/components/mc/ApiExecution";
import StageActions from "@/components/mc/StageActions";
import StepHeading from "@/components/mc/StepHeading";
import { Card } from "@/components/mc/ui";
import { buildLeaderboard } from "@/lib/caseset/leaderboard";
import type { Benchmark } from "@/lib/caseset/metrics";
import { agentPrompt } from "@/lib/caseset/prompts";
import { stepHref } from "@/lib/caseset/routes";
import { noharmHref } from "@/lib/noharm-path";
import { isTutorialProject } from "@/lib/onboarding";
import workspaceStyles from "../WelcomeWorkspace.module.css";
import { TextV2Leaderboard, textV2LeaderboardRows, type TextV2LeaderboardRow } from "@/components/mc/TextV2Results";

export function leaderboardExportRows(rows: TextV2LeaderboardRow[]): Record<string, unknown>[] {
  return rows.map(row => ({ model: row.model, prompt: row.prompt ?? "", prompt_sha256: row.promptSha256 ?? "", scored: row.scored, expected: row.expected, optimal: row.optimal, noError: row.none, mild: row.mild, moderate: row.moderate, severe: row.severe, unresolved: row.unresolved, worstErrorLowerBound: row.worstErrorLowerBound, worstErrorUpperBound: row.worstErrorUpperBound, provisionalCount: row.provisional, meanF1: row.meanF1, severeReviewReadings: row.severeReviewReadings, clinicianReviewedReadings: row.clinicianReviewed, scoresBehindReview: row.scoresBehindReview, severeReviewPending: row.pending, notFinal: row.incomplete, moreThanThreeRaters: row.moreThanThreeSlots, earlierGrading: row.previousPipeline }));
}

export default function LeaderboardStep({ bench }: { bench: Benchmark }) {
  const textCases = bench.cases.some(c => c.page.tables.some(table => table.textV2));
  const rows = textCases ? textV2LeaderboardRows(bench) : [];
  const textScored = rows.reduce((total, row) => total + row.scored, 0);
  const walkthrough = buildLeaderboard(bench);
  const scored = walkthrough.reduce((n, row) => n + row.scored, 0);
  const expected = walkthrough.reduce((n, row) => n + row.expected, 0);
  const exportRows = leaderboardExportRows(rows);
  return (
    <>
      <header className="mb-5 flex flex-wrap items-start gap-3.5">
        <StepHeading step="leaderboard" />

      </header>
      {textCases ? <TextV2Leaderboard bench={bench} /> : !bench.cases.length ? (
        <Card className="p-5">
          <h2 className="m-0 mb-2 text-[15px] font-semibold">Output</h2>
          <ApiStageAction project={bench.name} action={{ stage: "responses" }} label="Collect Responses" blocked="Add or import cases in Dataset first." apiLead="This project has no imported cases." lead="This project has no items yet. Ask your agent:" prompt={agentPrompt("import", undefined, bench.name)} />
        </Card>
      ) : (
        <Card className="px-5 py-4">
          <p className="m-0 text-[13.5px] text-mc-muted">Answer-table rubrics are no longer shown on the leaderboard. <Link className="text-mc-accent underline-offset-4 hover:underline" href={stepHref("scores")}>Inspect scores</Link></p>
        </Card>
      )}
      {isTutorialProject(bench.name) && expected > 0 && scored === expected && <Card className="mt-5 p-5">
        <h2 className="m-0 text-lg font-semibold">Your walkthrough is complete</h2>
        <p className="m-0 mt-2 text-sm text-mc-muted">You’ve built a practice benchmark through the full pipeline. Create your own project to work with your own dataset at your pace.</p>
        <Link className={workspaceStyles.primaryAction} href={noharmHref("/welcome?mode=new")}>Create a new project</Link>
      </Card>}
        {bench.name !== "__guided-uti__" && <StageActions step="leaderboard" project={bench.name} blocked={!textScored ? "Compute scores before exporting results." : undefined} exportRows={exportRows} />}
    </>
  );
}

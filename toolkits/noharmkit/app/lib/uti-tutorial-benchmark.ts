import path from "node:path";

import type { AnswerTableCase } from "@/lib/answer-table";
import { loadBenchmark, type Benchmark } from "@/lib/caseset/metrics";
import { KIT_ROOT, NotFoundError } from "@/lib/caseset/paths";
import { resolveStepParams } from "@/lib/caseset/routes";
import { datasetFields } from "@/lib/dataset-fields";
import { TUTORIAL_CASE, type TutorialDataset } from "@/lib/uti-tutorial";
export { TUTORIAL_CASE } from "@/lib/uti-tutorial";

export const TUTORIAL_PROJECT = "__guided-uti__";
export const BUNDLED_PROJECTS_ROOT = path.join(KIT_ROOT, "projects");

export function tutorialBenchmark(): Benchmark {
  const demo = loadBenchmark(BUNDLED_PROJECTS_ROOT, "demo");
  return {
    ...demo,
    name: TUTORIAL_PROJECT,
    cases: demo.cases.map((item) => ({ ...item, page: { ...item.page, caseset: TUTORIAL_PROJECT } })),
  };
}

export function tutorialRubric(version?: string): AnswerTableCase {
  const bench = tutorialBenchmark();
  const item = bench.cases.find((item) => item.caseId === TUTORIAL_CASE)!;
  const selected = version ?? resolveStepParams(bench, {}, "rubrics")?.version;
  const table = item.page.tables.find((table) => table.version === selected);
  if (!table?.record) throw new NotFoundError(`Unknown tutorial rubric ${selected}.`);
  return table.record;
}

export function tutorialDataset(): TutorialDataset {
  const source = tutorialBenchmark().cases.find((item) => item.caseId === TUTORIAL_CASE)!.page.source;
  const fields = datasetFields(source);
  return { task: fields.task, solution: fields.solutions[0], alternative: fields.solutions[1], errors: fields.errors };
}

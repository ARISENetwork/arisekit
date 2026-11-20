import type { DatasetCase } from "./dataset-import";
import type { CaseSource } from "./types";

export function datasetFields(source: CaseSource): DatasetCase {
  const record = source as CaseSource & { errors?: string | string[]; source_provenance?: { supplied_solutions?: string[] } };
  const errors = Array.isArray(record.errors) ? record.errors.join("\n") : record.errors ?? "";
  const supplied = record.source_provenance?.supplied_solutions;
  const suffix = `\n\nAuthor-provided error criteria (provisional harm levels):\n${errors}`;
  const solution = errors && source.recommendations.endsWith(suffix) ? source.recommendations.slice(0, -suffix.length) : source.recommendations;
  return { task: source.presentation, solutions: supplied?.length ? supplied : [solution], errors };
}

export function nextCaseId(ids: readonly string[]): string {
  const highest = Math.max(0, ...ids.map((id) => Number(/^Case(\d+)$/.exec(id)?.[1] ?? 0)));
  return `Case${String(highest + 1).padStart(3, "0")}`;
}

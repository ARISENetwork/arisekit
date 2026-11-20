import type { CasePage } from "@/lib/caseset/types";

// The banner may go only when a clinician-reviewed table passes and every judged response was judged against
// a passing reviewed table. A response judged against a generated run stays provisional.
export function needsProvisionalBanner(page: Pick<CasePage, "tables" | "responses">): boolean {
  const reviewed = new Set(page.tables.filter((t) => t.kind === "reviewed" && t.status === "pass").map((t) => t.version));
  if (reviewed.size === 0) return true;
  return page.responses.some((r) => r.record !== null && !reviewed.has(r.record.rubric));
}

// The editor opens one version. Only a passing reviewed copy is free of the banner; a generated run, the
// failed copy is still an LLM draft.
export function editorNeedsBanner(page: Pick<CasePage, "tables">, version: string): boolean {
  const opened = page.tables.find((t) => t.version === version);
  return !(opened && opened.kind === "reviewed" && opened.status === "pass");
}

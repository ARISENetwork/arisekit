import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { caseIds, inside } from "@/lib/caseset/paths";
import { parseDataset, type DatasetCase } from "@/lib/dataset-import";
import { readDatasetDrafts } from "@/lib/dataset-drafts";
import type { ApiPipelineAction } from "@/lib/api-pipeline-action";

export interface PipelineImport {
  id: string;
  case: { presentation: string; recommendations: string; errors: string; source_provenance: Record<string, unknown> };
}

export function preparePipelineDataset(root: string, project: string, action: ApiPipelineAction): PipelineImport[] {
  if (!action.sourceId && !action.draftKey) return [];
  const folder = inside(root, project);
  let records: DatasetCase[];
  let bytes: string;
  let source: Record<string, string>;
  if (action.sourceId) {
    bytes = readFileSync(inside(folder, ...action.sourceId.split("/")), "utf8");
    records = parseDataset(bytes, path.basename(action.sourceId));
    source = { source_file: action.sourceId };
  } else {
    const state = readDatasetDrafts(root, project);
    if (!Object.hasOwn(state.drafts, action.draftKey!)) throw new TypeError("The selected dataset draft is no longer available.");
    bytes = JSON.stringify(state.drafts[action.draftKey!]);
    records = parseDataset(bytes, "draft.json");
    source = { source_draft_key: action.draftKey! };
  }
  const hash = createHash("sha256").update(bytes).digest("hex");
  const existing = caseIds(folder);
  const occupied = new Set(existing);
  let next = 1;
  return records.map((record, index) => {
    const prior = existing.find(id => {
      const stored = JSON.parse(readFileSync(inside(folder, "cases", `${id}.json`), "utf8")).source_provenance;
      return stored?.source_sha256 === hash && stored.row === index + 1 && Object.entries(source).every(([key, value]) => stored[key] === value);
    });
    let id = prior ?? record.id;
    if (!id || !/^[A-Za-z0-9_]+$/.test(id)) {
      do { id = `Case${String(next++).padStart(3, "0")}`; } while (occupied.has(id));
    } else if (!prior && occupied.has(id)) throw new TypeError(`${id} already exists. Preserve its evidence and use a different case ID or project.`);
    occupied.add(id);
    const reference = record.solutions.length === 1 ? record.solutions[0] : record.solutions.map((solution, at) => `Acceptable solution ${at + 1}:\n${solution}`).join("\n\n");
    return { id, case: { presentation: record.task,
      recommendations: reference + (record.errors ? `\n\nAuthor-provided error criteria (provisional harm levels):\n${record.errors}` : ""), errors: record.errors,
      source_provenance: { ...source, source_sha256: hash, row: index + 1, supplied_solutions: record.solutions, ...((record.source_item_id ?? record.id) ? { source_item_id: record.source_item_id ?? record.id } : {}) },
    } };
  });
}

import { existsSync, readFileSync, readdirSync, realpathSync } from "node:fs";
import path from "node:path";
import { inside, KIT_ROOT } from "./caseset/paths";
import type { CaseSource } from "./types";

export function datasetSources(projectDir: string, cases: readonly { id: string; source: CaseSource }[]): { filename: string; path: string; processed: boolean }[] {
  const provenanceFile = inside(projectDir, "provenance.json");
  const provenance = existsSync(provenanceFile) ? JSON.parse(readFileSync(provenanceFile, "utf8")) as { case_source?: string } : {};
  const importedSourceDirectory = provenance.case_source ? path.resolve(KIT_ROOT, provenance.case_source) : undefined;
  const folder = inside(projectDir, "imports");
  if (!existsSync(folder)) return [];
  const used = new Set(cases.flatMap(({ source }) => {
    const file = (source as CaseSource & { source_provenance?: { source_file?: string } }).source_provenance?.source_file;
    const resolved = file ? file.startsWith("imports/") ? inside(projectDir, ...file.split("/")) : path.resolve(KIT_ROOT, file) : null;
    return resolved ? [existsSync(resolved) ? realpathSync(resolved) : resolved] : [];
  }));
  return readdirSync(folder, { withFileTypes: true }).filter((entry) => entry.isDirectory()).flatMap((entry) => {
    const subfolder = inside(projectDir, "imports", entry.name);
    return readdirSync(subfolder, { withFileTypes: true }).filter((file) => file.isFile() && /\.(csv|json)$/i.test(file.name) && !cases.some(({ id }) => importedSourceDirectory && path.resolve(importedSourceDirectory, `${id}.json`) === path.join(subfolder, file.name))).map((file) => {
      const sourcePath = inside(projectDir, "imports", entry.name, file.name);
      return { filename: file.name, path: sourcePath, processed: used.has(sourcePath) };
    });
  });
}

import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { casesetDir, inside } from "@/lib/caseset/paths";

export interface DatasetUpload { project: string; filename: string; path: string; bytes: number }

export function saveDatasetUpload(root: string, project: string, filename: string, bytes: Uint8Array): DatasetUpload {
  if (path.basename(filename) !== filename || filename.includes("\\") || !/\.(csv|json)$/i.test(filename)) throw new TypeError("Choose a CSV or JSON file with a plain filename.");
  const projectDir = casesetDir(root, project);
  const folder = inside(projectDir, "imports", randomUUID());
  mkdirSync(folder, { recursive: true });
  const target = inside(projectDir, "imports", path.basename(folder), filename);
  writeFileSync(target, bytes, { flag: "wx" });
  return { project, filename, path: target, bytes: bytes.byteLength };
}

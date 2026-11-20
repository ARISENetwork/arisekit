import { lstatSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { inside } from "./caseset/paths";

const SNAPSHOT_BYTES = 16 * 1024 * 1024;
export type ProjectFiles = Record<string, string>;

export class ProjectFileError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}

export function projectFailureStatus(error: unknown, fallback: number): number {
  return error instanceof ProjectFileError ? error.status : fallback;
}

export function validateProjectFiles(files: ProjectFiles): void {
  for (const [name, bytes] of Object.entries(files)) {
    const relative = name.endsWith("/") && bytes === "" ? name.slice(0, -1) : name;
    if (!relative || relative.startsWith("/") || relative.includes("\\") || relative.split("/").some(part => !part || part === "." || part === "..") || typeof bytes !== "string") throw new ProjectFileError("Invalid project file path.", 400);
  }
  const json = Buffer.from(JSON.stringify(files));
  if (json.byteLength > SNAPSHOT_BYTES) throw new ProjectFileError("This project exceeds the 16 MiB import limit.", 413);
}

export function filesIn(folder: string): ProjectFiles {
  const files: ProjectFiles = Object.create(null);
  const walk = (relative: string) => {
    const entries = readdirSync(path.join(folder, relative), { withFileTypes: true });
    if (relative && entries.length === 0) files[`${relative}/`] = "";
    for (const entry of entries) {
      if (entry.name.startsWith(".") || ["node_modules", "venv", "__pycache__"].includes(entry.name)) continue;
      const name = relative ? `${relative}/${entry.name}` : entry.name;
      const target = inside(folder, ...name.split("/"));
      if (lstatSync(target).isSymbolicLink()) throw new ProjectFileError("Project links cannot be copied.", 400);
      if (entry.isDirectory()) walk(name);
      else if (entry.isFile()) files[name] = readFileSync(target).toString("base64");
    }
  };
  walk("");
  return files;
}

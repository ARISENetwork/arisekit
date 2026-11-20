import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { inside } from "@/lib/caseset/paths";
import { projectMode } from "@/lib/project-mode";
import { validateProjectFiles, ProjectFileError, type ProjectFiles } from "@/lib/project-files";

export function importProject(root: string, name: unknown, raw: unknown): string {
  if (typeof name !== "string" || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(name)) throw new ProjectFileError("Use the original project folder, with a lowercase name containing letters, numbers, and hyphens.", 400);
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new ProjectFileError("Choose a NOHARMKit project folder.", 400);
  const files = raw as ProjectFiles;
  validateProjectFiles(files);
  for (const [file, bytes] of Object.entries(files)) {
    if (file.split("/").some(part => part.startsWith(".") || ["node_modules", "venv", "__pycache__"].includes(part))) throw new ProjectFileError("Choose only the project files; hidden files and dependency folders cannot be imported.", 400);
    if (Buffer.from(bytes, "base64").toString("base64") !== bytes) throw new ProjectFileError("A project file has invalid encoded content. Choose the folder again.", 400);
  }
  if (!Object.hasOwn(files, "provenance.json") || !Object.keys(files).some(file => file.startsWith("cases/") && file.endsWith(".json"))) throw new ProjectFileError("Choose the project folder containing provenance.json and its cases folder.", 400);
  let provenance;
  try { provenance = JSON.parse(Buffer.from(files["provenance.json"], "base64").toString("utf8")); }
  catch { throw new ProjectFileError("The project's provenance.json could not be read.", 400); }
  if (!provenance || typeof provenance !== "object" || Array.isArray(provenance) || provenance.caseset_name !== name) throw new ProjectFileError("The folder name must match the original project name in provenance.json.", 400);
  projectMode(provenance.execution_mode);
  const folder = inside(root, name);
  if (existsSync(folder)) throw new ProjectFileError("A project with this name already exists. Existing projects are never replaced by an import.", 409);
  mkdirSync(folder);
  try {
    for (const [file, bytes] of Object.entries(files)) {
      const target = inside(folder, ...file.replace(/\/$/, "").split("/"));
      if (file.endsWith("/")) mkdirSync(target, { recursive: true });
      else {
        mkdirSync(path.dirname(target), { recursive: true });
        writeFileSync(target, Buffer.from(bytes, "base64"), { flag: "wx" });
      }
    }
  } catch (error) {
    rmSync(folder, { recursive: true, force: true });
    throw error;
  }
  return name;
}

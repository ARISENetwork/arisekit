import { createHash, randomUUID } from "node:crypto";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { casesetDir, inside } from "@/lib/caseset/paths";
import { isTutorialProject } from "@/lib/onboarding";
import { initialModelTeams } from "@/lib/api-model-teams";
import { loadApiPipelineConfig } from "@/lib/api-pipeline-store";

export interface ResponsePrompt { id: string; name: string; text: string; sha256: string; savedAt: string }

const LOCKED = "This prompt has collected responses. Save your changes as a new prompt.";
const PROMPT_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;

export function promptId(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function readProvenance(folder: string): { synthetic?: boolean; inference?: { set_prompts?: Record<string, { id: string; sha256: string }> } } {
  const file = inside(folder, "provenance.json");
  return existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : {};
}

export function loadPrompts(root: string, project: string): ResponsePrompt[] {
  const file = inside(casesetDir(root, project), "prompts.json");
  if (!existsSync(file)) return [];
  const data = JSON.parse(readFileSync(file, "utf8")) as { prompts?: ResponsePrompt[] };
  if (!Array.isArray(data.prompts)) throw new TypeError("Malformed prompts.json: prompts must be a list.");
  return data.prompts;
}

function recordedPromptIds(root: string, project: string): Set<string> {
  const setPrompts = readProvenance(casesetDir(root, project)).inference?.set_prompts ?? {};
  return new Set(Object.values(setPrompts).map(entry => entry.id));
}

function configuredPromptIds(root: string, project: string): Set<string> {
  const config = loadApiPipelineConfig(root, project);
  return new Set(config ? initialModelTeams(config).responses.prompts ?? [] : []);
}

export function usedPromptIds(root: string, project: string): Set<string> {
  return new Set([...recordedPromptIds(root, project), ...configuredPromptIds(root, project)]);
}

export function recordedPromptHashes(root: string, project: string): Record<string, string> {
  const setPrompts = readProvenance(casesetDir(root, project)).inference?.set_prompts ?? {};
  return Object.fromEntries(Object.values(setPrompts).map(entry => [entry.id, entry.sha256]));
}

function writePrompts(folder: string, prompts: ResponsePrompt[]): void {
  const temporary = inside(folder, `.prompts-${randomUUID()}.tmp`);
  writeFileSync(temporary, `${JSON.stringify({ version: 1, prompts }, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, inside(folder, "prompts.json"));
}

function assertWritable(root: string, project: string): string {
  const folder = casesetDir(root, project);
  if (isTutorialProject(project) || project === "demo" && readProvenance(folder).synthetic === true) throw new TypeError("The prepared demo is read-only. Create your own project before saving prompts.");
  return folder;
}

export function savePrompt(root: string, project: string, input: { name: string; text: string; replaces?: string }): ResponsePrompt {
  const folder = assertWritable(root, project);
  const name = input.name.trim();
  const text = input.text.trim();
  const id = promptId(name);
  if (name.length < 1 || name.length > 64 || !PROMPT_ID.test(id)) throw new TypeError("Prompt name must be 1 to 64 characters and include a letter or number.");
  if (text.length < 1 || text.length > 20000) throw new TypeError("Prompt text must be 1 to 20000 characters.");
  const prompts = loadPrompts(root, project);
  if (input.replaces !== undefined) {
    if (!prompts.some(prompt => prompt.id === input.replaces)) throw new TypeError(`Prompt ${input.replaces} does not exist.`);
    const previous = prompts.find(prompt => prompt.id === input.replaces)!;
    if (recordedPromptIds(root, project).has(input.replaces)) throw new TypeError(LOCKED);
    if ((id !== previous.id || text !== previous.text) && configuredPromptIds(root, project).has(input.replaces)) throw new TypeError(LOCKED);
  }
  if (prompts.some(prompt => prompt.id === id && prompt.id !== input.replaces)) throw new TypeError(`A prompt named ${id} already exists. Choose another name.`);
  const saved: ResponsePrompt = { id, name, text, sha256: createHash("sha256").update(text, "utf8").digest("hex"), savedAt: new Date().toISOString() };
  const index = prompts.findIndex(prompt => prompt.id === input.replaces);
  writePrompts(folder, index < 0 ? [...prompts, saved] : prompts.map((prompt, at) => at === index ? saved : prompt));
  return saved;
}

export function deletePrompt(root: string, project: string, id: string): void {
  const folder = assertWritable(root, project);
  const prompts = loadPrompts(root, project);
  if (!prompts.some(prompt => prompt.id === id)) throw new TypeError(`Prompt ${id} does not exist.`);
  if (usedPromptIds(root, project).has(id)) throw new TypeError(LOCKED);
  writePrompts(folder, prompts.filter(prompt => prompt.id !== id));
}

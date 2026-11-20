import { readFile } from "node:fs/promises";
import path from "node:path";
import type { ProjectReviewPacket, ReviewPacket } from "./portable-review";
import { renderPortableHtml, type PortableProgress, type PortableShell } from "./portable-html";

export async function buildPortableHtml(packet: ReviewPacket | ProjectReviewPacket, appRoot = process.cwd(), progress?: PortableProgress): Promise<string> {
  const shell = JSON.parse(await readFile(path.join(appRoot, "portable/editor-shell.json"), "utf8")) as PortableShell;
  return renderPortableHtml(packet, shell, progress);
}

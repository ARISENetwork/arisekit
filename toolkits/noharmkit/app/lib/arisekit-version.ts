import { readFileSync } from "node:fs";
import path from "node:path";
import { KIT_ROOT } from "@/lib/caseset/paths";

export function projectVersion(): string {
  return readFileSync(path.resolve(KIT_ROOT, "../../VERSION"), "utf8").trim();
}

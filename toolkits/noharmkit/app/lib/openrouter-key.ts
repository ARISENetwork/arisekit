import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";
import { KIT_ROOT } from "@/lib/caseset/paths";
// The server's own environment wins, then the kit .env, then the repository-root .env.
export function openRouterApiKey(kitRoot = KIT_ROOT, env: Readonly<Record<string, string | undefined>> = process.env): string | undefined {
  if (env.OPENROUTER_API_KEY) return env.OPENROUTER_API_KEY;
  for (const file of [path.join(kitRoot, ".env"), path.resolve(kitRoot, "../../.env")]) {
    const key = existsSync(file) ? parseEnv(readFileSync(file, "utf8")).OPENROUTER_API_KEY : undefined;
    if (key) return key;
  }
  return undefined;
}

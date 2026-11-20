import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const APP = path.resolve(import.meta.dirname, "..");
const resolve = (spec: string): string | null => {
  if (!spec.startsWith("@/")) return null;
  const base = path.join(APP, spec.slice(2));
  return [".tsx", ".ts"].map(ext => base + ext).find(existsSync) ?? null;
};

// Server components cannot call functions exported from a "use client" module; only components (capitalized) and default exports survive.
const SERVER_PATH = ["components/mc/TextV2Results.tsx", "components/mc/steps/ScoresStep.tsx", "components/mc/steps/LeaderboardStep.tsx", "components/mc/steps/AutogradingStep.tsx"];

for (const file of SERVER_PATH) {
  test(`${file} imports only components from "use client" modules`, () => {
    const source = readFileSync(path.join(APP, file), "utf8");
    assert.ok(!source.startsWith('"use client"'), `${file} is expected to be a server module`);
    for (const [, clause, spec] of source.matchAll(/^import (?!type\b)([^;]*?) from "([^"]+)";/gm)) {
      const target = resolve(spec);
      if (!target || !readFileSync(target, "utf8").startsWith('"use client"')) continue;
      const named = /\{([^}]*)\}/.exec(clause)?.[1].split(",").map(name => name.trim().replace(/^type\s+/, "").split(/\s+as\s+/)[0]).filter(Boolean) ?? [];
      const bad = named.filter(name => !/^[A-Z]/.test(name));
      assert.deepEqual(bad, [], `${file} imports non-component ${bad.join(", ")} from client module ${spec}`);
    }
  });
}

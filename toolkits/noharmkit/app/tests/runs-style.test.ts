import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";

// Check shared UI conventions on every run viewer file.
const TARGETS = ["app/page.tsx", "app/noharm", "app/api/runs", "components/runs", "components/mc", "lib/caseset", "lib/onboarding.ts", "lib/noharm-path.ts", "lib/roadmap.ts"];

function sources(): string[] {
  return TARGETS.flatMap((target) => {
    const full = path.join(process.cwd(), target);
    assert.ok(existsSync(full), `${target}: style target missing`);
    if (statSync(full).isFile()) return [full];
    return (readdirSync(full, { recursive: true }) as string[]).filter((f) => /\.tsx?$/.test(f)).map((f) => path.join(full, f));
  });
}

test("run viewer sources use no side accents, em dashes, or dynamic Tailwind class names", () => {
  const files = sources();
  assert.ok(files.length >= 5);
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    assert.doesNotMatch(text, /\bborder-[lrse](?=[-\s"`]|$)|border-(?:left|right)/m, `${file}: side accent`);
    assert.doesNotMatch(text, /\u2014/, `${file}: em dash`);
    assert.doesNotMatch(text, /\b(?:bg|text|border|ring|fill|stroke)-\$\{/, `${file}: dynamic Tailwind class`);
  }
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { addV2Criterion, isOmissionItem, isTextV2, setV2Score, validateTextV2 } from "../lib/rubric-text-v2";
import type { TextV2Case, V2Mode } from "../lib/rubric-text-v2";

const fixture = (name: string): unknown => JSON.parse(readFileSync(new URL(`../../tests/fixtures/text-v2/${name}`, import.meta.url), "utf8"));
const parity = fixture("rubric-text-v2-parity.json") as { cases: { name: string; case: unknown; draft: { errors: string[]; warnings: string[] }; scoring: { errors: string[]; warnings: string[] } }[] };

for (const example of parity.cases) {
  for (const mode of ["draft", "scoring"] as V2Mode[]) {
    test(`text rubric parity: ${example.name}, ${mode}`, () => {
      assert.deepEqual(validateTextV2(example.case, mode), example[mode]);
    });
  }
}

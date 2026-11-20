// Prints the app's save-time validation errors for one answer-table record as a JSON array.
// Usage (from app/): node --import tsx ../tools/validate_answer_table.ts <record.json>
import { readFileSync } from "node:fs";

import { validateAnswerTable } from "../app/lib/answer-table.ts";

let errors: string[];
try {
  errors = validateAnswerTable(JSON.parse(readFileSync(process.argv[2], "utf8")));
} catch (e) {
  errors = [`validator crashed: ${(e as Error).message}`];
}
console.log(JSON.stringify(errors));
process.exit(errors.length ? 1 : 0);

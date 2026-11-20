import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { datasetFields, nextCaseId } from "../lib/dataset-fields";
import { parseDataset, rubricHandoff } from "../lib/dataset-import";
import { datasetSources } from "../lib/dataset-sources";
import { eachCase } from "./cases";

// Each row is a dataset file and either the cases it parses to or the error that refuses it whole.
const DATASETS: Array<{ name: string; text: string; filename: string; expect: ReturnType<typeof parseDataset> | RegExp }> = [
  {
    name: "CSV preserves quoted commas, quotes, multiline errors, and every row",
    text: 'Task,Solution,Errors\r\n"Case, one","Say ""yes""","Error one\nError two"\r\nCase two,Answer two,\r\n', filename: "cases.csv",
    expect: [{ task: "Case, one", solutions: ['Say "yes"'], errors: "Error one\nError two" }, { task: "Case two", solutions: ["Answer two"], errors: "" }],
  },
  {
    name: "JSON accepts legacy fields and multiple solutions without merging cases",
    text: JSON.stringify([{ id: "A001", presentation: "Task", recommendations: "Answer" }, { task: "Second", solutions: ["A", "B"], errors: ["X", "Y"] }]), filename: "cases.json",
    expect: [{ id: "A001", task: "Task", solutions: ["Answer"], errors: "" }, { task: "Second", solutions: ["A", "B"], errors: "X\nY" }],
  },
  { name: "unclosed CSV quote", text: 'Task,Solution\n"unfinished,Answer', filename: "a.csv", expect: /unclosed/ },
  { name: "short CSV row", text: 'Task,Solution\nCase', filename: "a.csv", expect: /expected 2/ },
  { name: "JSON case without a solution", text: '[{"task":"A","solution":"B"},{"task":"C"}]', filename: "a.json", expect: /Case 2.*Solution/ },
  { name: "ambiguous JSON columns", text: '{"task":"A","input":"B","solution":"C"}', filename: "a.json", expect: /multiple columns/ },
];

test("parseDataset cases", () => eachCase(DATASETS, (c) => c.name, (c) => {
  if (c.expect instanceof RegExp) assert.throws(() => parseDataset(c.text, c.filename), c.expect);
  else assert.deepEqual(parseDataset(c.text, c.filename), c.expect);
}));
test("handoff includes every case, alternatives, source, and errors", () => {
  const cases = parseDataset('[{"task":"A","solutions":["B","C"],"errors":"D"},{"task":"E","solution":"F"}]', "source.json");
  const prompt = rubricHandoff(cases, "source.json", false);
  assert.match(prompt, /Source file: source.json/);
  assert.deepEqual(JSON.parse(prompt.split("Dataset:\n")[1]), cases);
  assert.doesNotMatch(prompt, /synthetic NOHARMKit/);
});

type DatasetSource = Parameters<typeof datasetFields>[0];
const APPENDIX_SOURCE = { presentation: "Task", recommendations: "Answer\n\nAuthor-provided error criteria (provisional harm levels):\nModerate: Wrong antibiotic", errors: "Moderate: Wrong antibiotic" };
const FIELDS: Array<{ name: string; source: DatasetSource; expected: ReturnType<typeof datasetFields> }> = [
  { name: "supplied errors separate from the labeled Reference appendix", source: APPENDIX_SOURCE, expected: { task: "Task", solutions: ["Answer"], errors: APPENDIX_SOURCE.errors } },
  { name: "unrelated prose stays in the solution", source: { ...APPENDIX_SOURCE, recommendations: "Answer with unrelated prose" }, expected: { task: "Task", solutions: ["Answer with unrelated prose"], errors: APPENDIX_SOURCE.errors } },
  {
    name: "distinct supplied solutions and errors arrays",
    source: { presentation: "T", recommendations: "A", errors: ["E1", "E2"], source_provenance: { supplied_solutions: ["A", "B"] } } as DatasetSource,
    expected: { task: "T", solutions: ["A", "B"], errors: "E1\nE2" },
  },
  { name: "legacy reference", source: { presentation: "T", recommendations: "A" }, expected: { task: "T", solutions: ["A"], errors: "" } },
];

test("datasetFields cases", async () => {
  const before = JSON.stringify(APPENDIX_SOURCE);
  await eachCase(FIELDS, (c) => c.name, (c) => {
    assert.deepEqual(datasetFields(c.source), c.expected);
  });
  // Splitting never changes the source.
  assert.equal(JSON.stringify(APPENDIX_SOURCE), before);
});
test("new names continue the generic sequence and ignore content-derived IDs", () => {
  assert.equal(nextCaseId(["UTI001", "Case001", "Case004"]), "Case005");
  assert.equal(nextCaseId([]), "Case001");
});
test("upload status is derived from explicit source provenance, not the existence of any case", () => {
  const project = mkdtempSync(path.join(os.tmpdir(), "dataset-sources-"));
  mkdirSync(path.join(project, "imports", "upload"), { recursive: true });
  const file = path.join(project, "imports", "upload", "source.csv");
  writeFileSync(file, "Task,Solution\nT,A");
  assert.equal(datasetSources(project, [])[0].processed, false);
  const source = { presentation: "T", recommendations: "A", source_provenance: { source_file: file } };
  assert.equal(datasetSources(project, [{ id: "Case001", source }])[0].processed, true);
});

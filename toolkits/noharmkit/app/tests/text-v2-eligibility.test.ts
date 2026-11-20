import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

import { newTiming } from "../lib/answer-table";
import { loadEditorPayload, saveReviewedTable, ValidationError } from "../lib/caseset/editor";
import { loadTableVersion } from "../lib/caseset/read";
import { pipelinePython } from "../lib/pipeline-runner";
import { validateTextV2, V2_OMISSION_TEXT, type TextV2Case, type V2Mode } from "../lib/rubric-text-v2";
import { textV2ScoringErrors, validateTextV2ForProject, withoutDecisionRefs } from "../lib/text-v2-eligibility";
import { TEXT_V2_CURRENT_COMMIT, TEXT_V2_LEGACY_COMMIT, TEXT_V2_PIPELINE_V2_COMMIT } from "../lib/text-v2-runtime";
import { buildFixture, CASESET, writeCasesetFile } from "./caseset-fixture";

const current = { judge_scoring_source_commit: TEXT_V2_CURRENT_COMMIT };
const requiredMain = "C2: at least one non-optional appropriate item (score 7-9) is required";

test("people read validation findings without upstream decision numbers; the pinned messages keep them", () => {
  assert.equal(withoutDecisionRefs("C3.2: score 2 needs error severity at least mild (D147)"), "C3.2: score 2 needs error severity at least mild");
  assert.equal(withoutDecisionRefs("C2.1: omissionHarm belongs only to required counseling items (D127, D128)"), "C2.1: omissionHarm belongs only to required counseling items");
  assert.equal(withoutDecisionRefs("C2: needs a main approach"), "C2: needs a main approach");
});

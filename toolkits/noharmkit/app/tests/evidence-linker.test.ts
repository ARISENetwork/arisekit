import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { activeEvidence, EMPTY_EVIDENCE_SELECTION, evidenceSelection } from "../lib/caseset/evidence-selection";
import { loadBenchmark } from "../lib/caseset/metrics";
import { buildFixture, CASESET } from "./caseset-fixture";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const { EvidenceSelectionContext }: typeof import("../components/mc/EvidenceLinker") = require("../components/mc/EvidenceLinker");
const EvidenceMatch: typeof import("../components/mc/EvidenceMatch").default = require("../components/mc/EvidenceMatch").default;
const PipelineMarkdown: typeof import("../components/mc/Markdown").default = require("../components/mc/Markdown").default;
const AutogradingStep: typeof import("../components/mc/steps/AutogradingStep").default = require("../components/mc/steps/AutogradingStep").default;
const StepFrame: typeof import("../components/mc/StepFrame").default = require("../components/mc/StepFrame").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const first = { id: "D1:r0", keys: ["D1:r0"] };
const second = { id: "D2:r0", keys: ["D2:r0"] };

test("evidence selection follows pointer, keyboard, missing items, and dismissal, ignoring stale exit events", () => {
  let state = evidenceSelection(EMPTY_EVIDENCE_SELECTION, { type: "hover", target: first });
  assert.deepEqual(activeEvidence(state), first);
  state = evidenceSelection(state, { type: "hover", target: second });
  state = evidenceSelection(state, { type: "leave", id: first.id });
  assert.deepEqual(activeEvidence(state), second);
  state = evidenceSelection(state, { type: "focus", target: first });
  assert.deepEqual(activeEvidence(state), first);
  state = evidenceSelection(state, { type: "blur", id: second.id });
  assert.deepEqual(activeEvidence(state), first);
  state = evidenceSelection(state, { type: "blur", id: first.id });
  assert.deepEqual(activeEvidence(state), second);
  state = evidenceSelection(state, { type: "leave", id: second.id });
  assert.equal(activeEvidence(state), null);
  state = evidenceSelection(EMPTY_EVIDENCE_SELECTION, { type: "focus", target: first });
  state = evidenceSelection(state, { type: "hover", target: { id: "D3:missing", keys: [] } });
  assert.deepEqual(activeEvidence(state)?.keys, []);
  state = evidenceSelection(state, { type: "dismiss" });
  assert.equal(activeEvidence(state), null);
  assert.equal(state.focused, null);
  assert.equal(state.hovered, null);
});

test("the shared selection emphasizes only associated spans, including overlapping Markdown evidence", () => {
  const render = (active: { id: string; keys: string[] } | null) => renderToStaticMarkup(createElement(EvidenceSelectionContext.Provider, { value: { active, dispatch: () => {} } },
    createElement("div", null,
      createElement(PipelineMarkdown, { children: "Start **apixaban** now.", evidenceSpans: [
        { key: first.id, label: "Drug", evidence: "Start **apixaban**" },
        { key: second.id, label: "Timing", evidence: "**apixaban** now." },
      ] }),
      createElement(EvidenceMatch, { id: "missing", spanKeys: [], missing: true, note: "No supporting span was mapped in Input.", children: "Missing item" }),
    )));
  const selectedText = (html: string) => [...html.matchAll(/<mark\b([^>]*)>([^<]*)<\/mark>/g)].filter((mark) => mark[1].includes('data-evidence-active="true"')).map((mark) => mark[2]).join("");
  assert.equal(selectedText(render(first)), "Start apixaban");
  assert.equal(selectedText(render(second)), "apixaban now.");
  const missing = render({ id: "missing", keys: [] });
  assert.equal(selectedText(missing), "");
  assert.match(missing, /aria-hidden="true"[^>]*role="tooltip">No supporting span was mapped in Input/);
  const description = /aria-describedby="([^"]+)"/.exec(missing)![1];
  assert.ok(missing.includes(`id="${description}"`));
  assert.doesNotMatch(render(null), /data-evidence-active="true"|aria-hidden="false"/);
});

test("autograding shows stored rubric scores and distinct missing states without copying the response into Output", () => {
  const fixture = buildFixture();
  const bench = loadBenchmark(fixture.root, CASESET);
  const c = bench.cases[0];
  const row = c.responses[0].row;
  const table = c.page.tables.find((entry) => entry.version === row.record!.rubric)!.record!;
  table.decisions.push({ id: "D3", question: "Is further investigation needed?", activation: { type: "always" }, recommendations: [] });
  row.record!.judge!.decisions.D1.recommended![0].evidence = "Evidence absent from the response.";
  const params = { caseId: c.caseId, itemId: row.itemId, model: row.model, trial: row.trial, version: "run1" };
  const before = JSON.stringify(bench);
  const page = AutogradingStep({ bench, params });
  const output = renderToStaticMarkup(page.props.outputs);
  const d1 = /<button[^>]*data-evidence-match="D1:r0"[\s\S]*?<\/button>/.exec(output)![0];
  assert.match(d1, /Refer to cardiology\./);
  assert.match(d1, /Evidence not found/);
  assert.match(d1, />8<\/span>/);
  const d3 = /<button[^>]*data-evidence-match="D3:missing"[\s\S]*?<\/button>/.exec(output)![0];
  assert.match(d3, /No recommendation mapped/);
  assert.match(d3, />-<\/span>/);
  assert.doesNotMatch(d3, />0<\/span>/);
  assert.match(output, /No supporting span was mapped in Input/);
  assert.match(output, /F1 1\.000/);
  assert.doesNotMatch(output, /Refer to cardiology within a month\./);
  const input = renderToStaticMarkup(page.props.inputs);
  assert.match(input, /<mark[^>]*data-evidence-keys="\[&quot;D2:r0&quot;\]"/);
  const frame = StepFrame(page.props);
  assert.ok(frame.key?.includes(row.model));
  const other = AutogradingStep({ bench, params: { ...params, trial: 2 } });
  assert.equal(other.props.evidenceLinked, false);
  assert.equal(JSON.stringify(bench), before);
});

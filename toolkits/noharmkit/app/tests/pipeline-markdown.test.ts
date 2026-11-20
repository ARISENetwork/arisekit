import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { createElement } from "react";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { renderToStaticMarkup } from "react-dom/server";
import { test } from "node:test";

import { loadBenchmark } from "../lib/caseset/metrics";
import { buildFixture, CASESET } from "./caseset-fixture";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
const PipelineMarkdown: typeof import("../components/mc/Markdown").default = require("../components/mc/Markdown").default;
const CasesStep: typeof import("../components/mc/steps/CasesStep").default = require("../components/mc/steps/CasesStep").default;
const RubricsStep: typeof import("../components/mc/steps/RubricsStep").default = require("../components/mc/steps/RubricsStep").default;
const ResponsesStep: typeof import("../components/mc/steps/ResponsesStep").default = require("../components/mc/steps/ResponsesStep").default;
const AutogradingStep: typeof import("../components/mc/steps/AutogradingStep").default = require("../components/mc/steps/AutogradingStep").default;
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

const render = (text: string, inline = false): string => renderToStaticMarkup(createElement(PipelineMarkdown, { children: text, inline }));

test("clinical Markdown renders headings, lists, emphasis, links, aligned tables, task lists, code, and accessible footnotes", () => {
  const clinical = "## Plan\n\n1. **First action**\n   - A supporting *detail*.\n2. Another action.\n\n[Source](https://example.org/reference)\n\n| Finding | Value |\n| --- | --- |\n| A | B |\n\n```text\nraw <value>\n```";
  const extended = "| Name | Count |\n| :--- | ---: |\n| A | 2 |\n\n- [x] Complete\n- [ ] Pending\n\nA statement[^1].\n\n[^1]: Supporting reference.";
  // Rendered separately so the extended document's task list and footnotes cannot satisfy the clinical list checks.
  const html = render(clinical);
  assert.match(html, /<h4[^>]*>Plan<\/h4>/);
  assert.match(html, /<ol\b/);
  assert.match(html, /<ul\b/);
  assert.match(html, /<strong>First action<\/strong>/);
  assert.match(html, /<em>detail<\/em>/);
  assert.match(html, /href="https:\/\/example.org\/reference"/);
  assert.match(html, /<table\b/);
  assert.match(html, /<th[^>]*>Finding<\/th>/);
  assert.match(html, /<td[^>]*>B<\/td>/);
  assert.match(html, /<pre\b/);
  assert.ok(html.includes("raw &lt;value&gt;"));
  assert.doesNotMatch(html, /max-w-\[|<p[^>]*>## Plan/);
  const gfm = render(extended);
  assert.match(gfm, /style="text-align:right"/);
  assert.match(gfm, /<input[^>]*type="checkbox"[^>]*disabled=""/);
  assert.match(gfm, /aria-describedby="md-[^"]+-footnote-label"/);
  assert.match(gfm, /<h4[^>]*id="md-[^"]+-footnote-label"/);
  assert.match(gfm, /data-footnote-backref=""/);
});

test("model text cannot execute embedded HTML or javascript URLs", () => {
  const html = render('<script>alert(1)</script>\n\n[Unsafe](javascript:alert%281%29)\n\n<img src="x" onerror="alert(1)">');
  assert.doesNotMatch(html, /<script|<img[^>]*onerror|href="javascript:/);
  assert.ok(html.includes("&lt;script&gt;"));
});

test("inline rubric text formats emphasis without putting paragraphs inside spans", () => {
  const html = render("Use **first choice** or `alternative`.", true);
  assert.match(html, /<strong>first choice<\/strong>/);
  assert.match(html, /<code[^>]*>alternative<\/code>/);
  assert.doesNotMatch(html, /<p\b|<div\b/);
});

test("question and answer footnotes link within their own Markdown panel", () => {
  const html = renderToStaticMarkup(createElement("div", null,
    createElement(PipelineMarkdown, { children: "Question[^1].\n\n[^1]: Question reference." }),
    createElement(PipelineMarkdown, { children: "Answer[^1].\n\n[^1]: Answer reference." }),
  ));
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  const links = [...html.matchAll(/<a\b[^>]*>/g)].map((match) => match[0]);
  const references = links.filter((tag) => /\bdata-footnote-ref=/.test(tag));
  assert.equal(references.length, 2);
  for (const tag of references) {
    const id = /\bid="([^"]+)"/.exec(tag)![1];
    const prefix = id.split("fnref-")[0];
    const target = /href="#([^"]+)"/.exec(tag)![1];
    assert.ok(target.startsWith(prefix));
    assert.ok(ids.includes(target));
    assert.ok(tag.includes(`aria-describedby="${prefix}footnote-label"`));
    assert.ok(ids.includes(`${prefix}footnote-label`));
    assert.ok(links.some((link) => link.includes('data-footnote-backref=""') && link.includes(`href="#${id}"`)));
  }
});

test("pipeline inputs and outputs render Markdown while keeping source evidence intact", () => {
  const fixture = buildFixture();
  const bench = loadBenchmark(fixture.root, CASESET);
  const c = bench.cases[0];
  const response = c.responses[0].row;
  const params = { caseId: c.caseId, itemId: response.itemId, model: response.model, trial: response.trial, version: "run1" };
  c.page.source.presentation = "## Case\n\nA **clinical detail**.";
  c.page.source.recommendations = "- **First action**\n- Alternative.";
  c.prompts[params.itemId] = "## Prompt\n\nA **recorded detail**.";
  response.response = "**Refer to cardiology within a month.**\n\nStart apixaban\n5 mg twice daily. Recheck in 2 weeks.";
  const table = c.page.tables.find((t) => t.version === "run1")!;
  table.record!.decisions[0].question = "What **follow-up** is appropriate?";
  table.record!.decisions[0].recommendations[0].text = "**Refer** to cardiology.";
  const before = JSON.stringify(bench);
  const cases = CasesStep({ bench, params });
  const source = renderToStaticMarkup(createElement("div", null, cases.props.inputs, cases.props.outputs));
  assert.equal(cases.props.inputsTitle, "Task");
  assert.equal(cases.props.outputsTitle, "Solution");
  assert.doesNotMatch(source, /Case file|No import record|cases\/.*\.json|max-w-\[/);
  assert.match(source, /<h4[^>]*>Case<\/h4>/);
  assert.match(source, /<strong>clinical detail<\/strong>/);
  assert.match(source, /<ul[^>]*>/);
  const rubric = RubricsStep({ bench, params });
  const rubricOutput = renderToStaticMarkup(createElement(AppRouterContext.Provider, { value: { back() {}, forward() {}, refresh() {}, bfcacheId: "test", push() {}, replace() {}, prefetch() {} } }, rubric.props.outputs));
  assert.match(renderToStaticMarkup(rubric.props.inputs), /<strong>First action<\/strong>/);
  assert.match(rubricOutput, /<strong>follow-up<\/strong>/);
  assert.doesNotMatch(rubricOutput, /<strong>Refer<\/strong>/);
  const responses = ResponsesStep({ bench, params });
  assert.match(renderToStaticMarkup(responses.props.inputs), /<strong>recorded detail<\/strong>/);
  assert.match(renderToStaticMarkup(responses.props.outputs), /<strong>Refer to cardiology within a month\.<\/strong>/);
  const autograding = AutogradingStep({ bench, params });
  const input = renderToStaticMarkup(autograding.props.inputs);
  const output = renderToStaticMarkup(autograding.props.outputs);
  assert.match(input, /<strong><mark[^>]*>Refer to cardiology within a month\.<\/mark><\/strong>/);
  assert.doesNotMatch(input, /Evidence highlights|Model response/);
  assert.match(input, /<mark[^>]*title="D2: Should anticoagulation start now\?\nD2.O1: Start apixaban 5 mg twice daily\."[^>]*>Start apixaban\n5 mg twice daily\.<\/mark>/);
  assert.match(output, /<strong>Refer<\/strong> to cardiology/);
  assert.match(output, /Rubric score \(1-9\)/);
  assert.doesNotMatch(output, /<mark|Refer to cardiology within a month\./);
  assert.equal(autograding.props.evidenceLinked, true);
  assert.equal(JSON.stringify(bench), before);
});

type EvidenceSpans = Parameters<typeof PipelineMarkdown>[0]["evidenceSpans"];
const HIGHLIGHT_CASES: { label: string; source: string; evidenceSpans: EvidenceSpans; match: RegExp[]; absent: RegExp[] }[] = [
  {
    label: "highlights cross Markdown formatting without flattening headings, lists, or tables",
    source: "## Plan\n\n- Start **apixaban** now.\n\n| Follow-up |\n| --- |\n| Recheck in 2 weeks. |",
    evidenceSpans: [
      { key: "D1:r0", label: "D1: Anticoagulation", evidence: "Start **apixaban** now." },
      { key: "off:0", label: "Off-rubric", evidence: "Recheck in 2 weeks." },
    ],
    match: [/<h4[^>]*>Plan<\/h4>/, /<ul\b/, /<mark[^>]*>Start <\/mark><strong><mark[^>]*>apixaban<\/mark><\/strong><mark[^>]*> now\.<\/mark>/, /<table\b/, /<mark[^>]*data-evidence-kind="unmapped"[^>]*>Recheck in 2 weeks\.<\/mark>/],
    absent: [],
  },
  {
    label: "decoded escapes, entities, and Unicode keep accurate boundaries",
    source: "Take \\*care\\* &amp; rest. Then review 🩺 symptoms.",
    evidenceSpans: [
      { key: "D1:r0", label: "Care", evidence: "\\*care\\* &amp; rest." },
      { key: "D2:r0", label: "Review", evidence: "🩺 symptoms" },
    ],
    match: [/Take <mark[^>]*>\*care\* &amp; rest\.<\/mark> Then review <mark[^>]*>🩺 symptoms<\/mark>\./],
    absent: [],
  },
  {
    label: "overlapping matches keep both rubric labels and cannot execute label HTML",
    source: "Start apixaban now.",
    evidenceSpans: [
      { key: "D1:r0", label: "<script>unsafe</script>", evidence: "Start apixaban" },
      { key: "D2:r0", label: "D2: Timing", evidence: "apixaban now." },
    ],
    match: [/title="&lt;script&gt;unsafe&lt;\/script&gt;\nD2: Timing"/, />apixaban<\/mark>/],
    absent: [/<script/],
  },
];

test("evidence highlight boundaries", () => eachCase(HIGHLIGHT_CASES, (c) => c.label, (c) => {
  const html = renderToStaticMarkup(createElement(PipelineMarkdown, { children: c.source, evidenceSpans: c.evidenceSpans }));
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
}));

test("autograding preserves missing evidence and hides highlights for stale or unverified judgments", () => {
  const fixture = buildFixture();
  const bench = loadBenchmark(fixture.root, CASESET);
  const c = bench.cases[0];
  const row = c.responses[0].row;
  const params = { caseId: c.caseId, itemId: row.itemId, model: row.model, trial: row.trial, version: "run1" };
  row.record!.judge!.decisions.D1.recommended![0].evidence = "A statement absent from this response.";
  const before = JSON.stringify(bench);
  const html = renderToStaticMarkup(AutogradingStep({ bench, params }).props.outputs);
  assert.match(html, /Evidence not found/);
  assert.match(html, /A statement absent from this response\./);
  assert.match(html, /aria-expanded="false"/);
  const input = renderToStaticMarkup(AutogradingStep({ bench, params }).props.inputs);
  assert.match(input, /data-evidence-kind="mapped"/);
  assert.match(input, /data-evidence-kind="unmapped"/);
  assert.equal(JSON.stringify(bench), before);
  for (const state of ["stale", "unverified", "failed"] as const) {
    row.judge = state;
    const output = renderToStaticMarkup(AutogradingStep({ bench, params }).props.outputs);
    assert.doesNotMatch(output, /<mark|Rubric matches/);
    assert.match(output, state === "stale" ? /Out of date/ : state === "unverified" ? /Unverified inputs/ : /Failed/);
    assert.doesNotMatch(renderToStaticMarkup(AutogradingStep({ bench, params }).props.inputs), /<mark/);
  }
});

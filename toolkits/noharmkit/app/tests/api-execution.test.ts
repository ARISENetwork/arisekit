import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { eachCase } from "./cases";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const { default: ApiExecutionProvider, ApiStageAction, ApiRunMetadata, consumeApiPipelineStream }: typeof import("../components/mc/ApiExecution") = require("../components/mc/ApiExecution");
const ModelChecklist: typeof import("../components/mc/ModelChecklist").default = require("../components/mc/ModelChecklist").default;
const { AppRouterContext } = require("next/dist/shared/lib/app-router-context.shared-runtime");
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

function stream(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({ start(controller) { chunks.forEach(chunk => controller.enqueue(chunk)); controller.close(); } });
}

const scoreRun = { jobId: "score-1", action: { stage: "score" as const }, status: "completed" as const, startedAt: "2026-10-25T12:00:00Z", finishedAt: "2026-10-25T12:00:02Z" };
const promptedRun = { jobId: "r-1", action: { stage: "responses" as const, prompt: "safety-first" }, status: "interrupted" as const };
type MetadataProps = Parameters<typeof ApiRunMetadata>[0];
const METADATA_CASES: { label: string; props: MetadataProps; match: RegExp[]; absent: RegExp[] }[] = [
  { label: "score run is local and deterministic", props: { run: scoreRun, now: 0 }, match: [/Local \/ deterministic/, /No model calls or API credits/, /0m 2s/], absent: [/OpenRouter|Workers|not recorded/] },
  { label: "responses run uses OpenRouter workers", props: { run: { ...scoreRun, action: { stage: "responses" } }, now: 0 }, match: [/API \/ OpenRouter/, /Workers/, /not recorded/], absent: [] },
  { label: "prompted run names the prompt and its full text", props: { run: promptedRun, now: 0, prompt: { state: "ok", id: "safety-first", name: "Safety first", text: "Answer as a cautious clinician.\nName the main risk." } }, match: [/Prompt: Safety first/, /Answer as a cautious clinician\./], absent: [] },
  { label: "prompted run says why it cannot resume", props: { run: promptedRun, now: 0, prompt: { state: "blocked", id: "safety-first", reason: "The prompt safety-first is no longer saved in this project." } }, match: [/Prompt: safety-first/, /no longer saved/], absent: [] },
  { label: "prompted run while the prompt is checked", props: { run: promptedRun, now: 0 }, match: [/Checking the saved prompt/], absent: [] },
  { label: "unprompted run names no prompt", props: { run: { ...promptedRun, action: { stage: "responses" as const } }, now: 0 }, match: [], absent: [/Prompt:/] },
];

test("run metadata", () => eachCase(METADATA_CASES, (c) => c.label, (c) => {
  const html = renderToStaticMarkup(createElement(ApiRunMetadata, c.props));
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
}));

test("pipeline event decoding preserves split UTF-8, chunk boundaries, and an unterminated final line", async () => {
  const events = [
    { type: "started", jobId: "job-1", message: "Rubric café", startedAt: "2026-10-25T12:00:00Z" },
    { type: "checkpoint", message: "Case001 saved" },
    { type: "result", status: "failed", error: "Provider quota exhausted" },
  ];
  const bytes = new TextEncoder().encode(events.map(event => JSON.stringify(event)).join("\r\n"));
  const received: unknown[] = [];
  await consumeApiPipelineStream(stream(Array.from(bytes, byte => new Uint8Array([byte]))), event => received.push(event));
  assert.deepEqual(received, events);
});

test("malformed events and transport errors reject without inventing a completed result", async () => {
  const received: unknown[] = [];
  await assert.rejects(consumeApiPipelineStream(stream([new TextEncoder().encode('{"type":"checkpoint"}\ninvalid\n')]), event => received.push(event)), SyntaxError);
  assert.deepEqual(received, [{ type: "checkpoint" }]);
  const failed = new ReadableStream<Uint8Array>({ start(controller) { controller.error(new Error("Connection lost after checkpoint")); } });
  await assert.rejects(consumeApiPipelineStream(failed, () => assert.fail("No event should be fabricated")), /Connection lost after checkpoint/);
});

function renderAction(mode: "api" | "local", configured: boolean, target = "example"): string {
  return renderToStaticMarkup(createElement(AppRouterContext.Provider, { value: { refresh() {} } },
    createElement(ApiExecutionProvider, { project: "example", mode, configured, children: createElement(ApiStageAction, {
      project: target, action: { stage: "responses" }, label: "Collect Responses", prompt: "Local handoff remains available.",
    }) })));
}

test("API model checklist links setup without showing Local instructions or choosing models", () => {
  const html = renderToStaticMarkup(createElement(AppRouterContext.Provider, { value: { refresh() {} } },
    createElement(ApiExecutionProvider, { project: "example", mode: "api", configured: false, children: createElement(ModelChecklist, { project: "example", plannedModels: ["retained/existing"] }) })));
  assert.match(html, /href="\/noharm\/api-setup"/);
  assert.doesNotMatch(html, /Copy model selection|type="checkbox"/);
});

const COLLECT_BUTTON = />Collect Responses<\/button>/;
const HANDOFF = /Local handoff remains available/;
const ACTION_CONTEXTS: { label: string; render: () => string; match: RegExp[]; absent: RegExp[] }[] = [
  { label: "configured API shows the button and its scope", render: () => renderAction("api", true), match: [/All imported cases, using the configured model and trial scope/, COLLECT_BUTTON], absent: [HANDOFF] },
  { label: "unconfigured API links setup", render: () => renderAction("api", false), match: [/Set up API models/], absent: [COLLECT_BUTTON] },
  { label: "Local Mode keeps the handoff", render: () => renderAction("local", true), match: [HANDOFF], absent: [COLLECT_BUTTON] },
  { label: "tutorial target keeps the handoff", render: () => renderAction("api", true, "__guided-uti__"), match: [HANDOFF], absent: [COLLECT_BUTTON] },
  { label: "another project keeps the handoff", render: () => renderAction("api", true, "another-project"), match: [HANDOFF], absent: [COLLECT_BUTTON] },
  { label: "no execution context keeps the copy prompt", render: () => renderToStaticMarkup(createElement(ApiStageAction, { project: "example", action: { stage: "score" }, label: "Compute Scores", prompt: "Use the scoring skill.", lead: "Ask your agent:" })), match: [/Use the scoring skill/, /Ask your agent:/], absent: [/>Compute Scores<\/button>/] },
];

test("stage actions choose a button or a handoff by context", () => eachCase(ACTION_CONTEXTS, (c) => c.label, (c) => {
  const html = c.render();
  for (const pattern of c.match) assert.match(html, pattern);
  for (const pattern of c.absent) assert.doesNotMatch(html, pattern);
}));

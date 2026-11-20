import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { NextRequest } from "next/server";
import { POST as saveConfig } from "../app/api/pipeline/config/route";
import { POST as runApi } from "../app/api/pipeline/run/route";
import { createProject } from "../lib/project-create";
import { generateRubricLabel, parseApiPipelineAction, pipelineSourceId } from "../lib/api-pipeline-action";
import { parseApiPipelineConfig, type ApiPipelineConfig, type ApiPipelineConfigV2 } from "../lib/api-pipeline-config";
import { loadApiPipelineConfig, saveApiPipelineConfig, validateApiModels } from "../lib/api-pipeline-store";
import { parseOpenRouterModels } from "../lib/openrouter-models";
import { localPipelineWorkspace } from "../lib/pipeline-workspace";
import { currentPipelineRun, executePipeline, pipelineActive, pipelinePython, stopPipelineRun, type PipelineEvent } from "../lib/pipeline-runner";
import { preparePipelineDataset } from "../lib/pipeline-dataset";
import { saveDatasetUpload } from "../lib/dataset-upload";
import { saveDatasetDrafts } from "../lib/dataset-drafts";
import { eachCase } from "./cases";

const config: ApiPipelineConfig = { version: 1, generationModel: "fixture/writer", ratingModels: [], responseModels: ["fixture/model"], judgeModel: "fixture/judge" };
const inspect = async () => ({ status: "ready" as const, operationIdentity: "fixture-operation", reusableCalls: 0 });
const teamConfig: ApiPipelineConfigV2 = { version: 2, teams: {
  generation: { models: ["fixture/writer", "fixture/model"], integrator: "fixture/writer", modelReasoning: { "fixture/writer": "low" }, integratorReasoning: { "fixture/writer": "high" } },
  rating: { models: [], integrator: "" },
  responses: { models: ["fixture/model"], integrator: "" },
  judge: { models: ["fixture/judge"], integrator: "" },
} };
const catalog = { data: ["writer", "model", "judge"].map(name => ({ id: `fixture/${name}`, name, context_length: 8192, architecture: { output_modalities: ["text"] }, supported_parameters: ["structured_outputs"], pricing: { prompt: "0.000001", completion: "0.000002" } })) };

function fixture(): { root: string; project: string } {
  const root = mkdtempSync(path.join(os.tmpdir(), "api-pipeline-test-"));
  createProject(root, "example", "", "api");
  saveApiPipelineConfig(root, "example", config);
  return { root, project: "example" };
}

function driver(folder: string): string {
  const file = path.join(folder, "fake-driver.py");
  writeFileSync(file, `import json, os, sys\nfrom pathlib import Path\nr=json.loads(sys.stdin.readline())\np=Path(r['project'])\nassert os.environ['OPENROUTER_API_KEY']=='fake-key'\nassert 'OPENAI_API_KEY' not in os.environ\nassert set(r['action']) <= {'stage','caseIds','rubric'}\n(p/'results').mkdir(exist_ok=True)\n(p/'results'/'checkpoint.json').write_text(json.dumps({'saved':True}))\nprint(json.dumps({'type':'checkpoint','stage':'responses'}),flush=True)\nassert json.loads(sys.stdin.readline())=={'type':'ack'}\n(p/'results'/'after-ack.json').write_text('{}')\nprint(json.dumps({'type':'result','status':'completed','errors':[]}),flush=True)\n`);
  return file;
}

test("API configuration rejects transport escapes and unavailable models", () => {
  assert.deepEqual(parseApiPipelineConfig(config), config);
  for (const generationModel of ["codex/gpt-model", "direct/model", "../model", "openai", "https://provider/model"]) assert.throws(() => parseApiPipelineConfig({ ...config, generationModel }));
  assert.throws(() => parseApiPipelineConfig({ ...config, responseModels: [] }));
  assert.throws(() => parseApiPipelineConfig({ ...config, ratingModels: ["fixture/model", "fixture/model"] }));
  const models = parseOpenRouterModels(catalog);
  assert.equal(models[0].inputPrice, "0.000001");
  validateApiModels(config, models);
  assert.throws(() => validateApiModels(config, models.filter(model => model.id !== config.judgeModel)), /fixture\/judge/);
  validateApiModels(config, [], "score");
  validateApiModels(config, models.filter(model => model.id !== config.judgeModel), "responses");
});

const PROMPT_STAGE = /A prompt belongs to response collection\./;
const REPLACE_STAGE = /belongs to response collection or autograding/;
const ACTION_CASES: { label: string; input: Record<string, unknown>; output?: Record<string, unknown>; error?: RegExp }[] = [
  { label: "generate defaults to text-v2", input: { stage: "generate" }, output: { stage: "generate", rubricFormat: "text-v2" } },
  { label: "generate keeps answer-table", input: { stage: "generate", rubricFormat: "answer-table" }, output: { stage: "generate", rubricFormat: "answer-table" } },
  { label: "generate refuses an unknown format", input: { stage: "generate", rubricFormat: "unknown" } },
  ...["responses", "judge", "score"].map(stage => ({ label: `rubricFormat refused on ${stage}`, input: { stage, rubricFormat: "text-v2" } })),
  { label: "judge keeps explicit caseIds", input: { stage: "judge", rubric: "reviewed-local", caseIds: ["Case001"] }, output: { stage: "judge", rubric: "reviewed-local", caseIds: ["Case001"] } },
  { label: "legacy judge without caseIds", input: { stage: "judge", rubric: "run1" }, output: { stage: "judge", rubric: "run1" } },
  ...[[], ["Case001", "Case001"], ["../Case001"]].map(caseIds => ({ label: `judge refuses caseIds ${JSON.stringify(caseIds)}`, input: { stage: "judge", rubric: "reviewed-local", caseIds } })),
  ...["responses", "score"].map(stage => ({ label: `caseIds refused on ${stage}`, input: { stage, caseIds: ["Case001"] } })),
  { label: "responses keeps a prompt", input: { stage: "responses", prompt: "safe-first" }, output: { stage: "responses", prompt: "safe-first" } },
  { label: "responses without a prompt", input: { stage: "responses" }, output: { stage: "responses" } },
  ...["generate", "judge", "score"].map(stage => ({ label: `prompt refused on ${stage}`, input: { stage, prompt: "safe-first" }, error: PROMPT_STAGE })),
  { label: "responses refuses a bad prompt id", input: { stage: "responses", prompt: "Not An Id" }, error: /prompt/i },
  ...["responses", "judge"].map(stage => ({ label: `${stage} keeps replaceOutdated`, input: { stage, replaceOutdated: true }, output: { stage, replaceOutdated: true } })),
  ...["generate", "score"].map(stage => ({ label: `replaceOutdated refused on ${stage}`, input: { stage, replaceOutdated: true }, error: REPLACE_STAGE })),
  { label: "score keeps allowPartial", input: { stage: "score", allowPartial: true }, output: { stage: "score", allowPartial: true } },
  ...["generate", "responses", "judge"].map(stage => ({ label: `allowPartial refused on ${stage}`, input: { stage, allowPartial: true, ...(stage === "judge" ? { rubric: "run1" } : {}) }, error: /Partial scoring belongs to scoring/ })),
  { label: "allowPartial false refused", input: { stage: "score", allowPartial: false }, error: /Partial scoring belongs to scoring/ },
  { label: "replaceOutdated false refused", input: { stage: "responses", replaceOutdated: false }, error: REPLACE_STAGE },
  { label: "transport escape: shell stage", input: { stage: "shell", command: "rm" } },
  { label: "transport escape: ../ caseId on generate", input: { stage: "generate", caseIds: ["../secret"] } },
  { label: "transport escape: ../ rubric on judge", input: { stage: "judge", rubric: "../../run1" } },
  { label: "transport escape: absolute sourceId", input: { stage: "generate", sourceId: "/tmp/imports/a/x.json" } },
];

test("typed pipeline actions accept only stage-scoped fields", () => eachCase(ACTION_CASES, (c) => c.label, (c) => {
  if (c.output) assert.deepEqual(parseApiPipelineAction(c.input), c.output);
  else if (c.error) assert.throws(() => parseApiPipelineAction(c.input), c.error);
  else assert.throws(() => parseApiPipelineAction(c.input));
}));

test("the dataset page names one rubric for one case and rubrics for several", () => {
  assert.equal(generateRubricLabel(["Case001"]), "Generate Rubric");
  assert.equal(generateRubricLabel(["Case001", "Case002"]), "Generate Rubrics");
  assert.equal(generateRubricLabel(undefined), "Generate Rubrics");
});

test("execution transports the action and full team config to the driver", async () => {
  for (const rubricFormat of ["text-v2", "answer-table"] as const) {
    const { root, project } = fixture();
    saveApiPipelineConfig(root, project, teamConfig);
    const workspace = localPipelineWorkspace(root, project);
    const file = path.join(workspace.root, "bridge-driver.py");
    writeFileSync(file, `import json, sys\nr=json.loads(sys.stdin.readline())\nassert r['action']=={'stage':'generate','rubricFormat':'${rubricFormat}'}\nassert r['config']==json.loads(${JSON.stringify(JSON.stringify(teamConfig))})\nprint(json.dumps({'type':'result','status':'completed','errors':[]}),flush=True)\n`);
    const action = parseApiPipelineAction({ stage: "generate", rubricFormat });
    const result = await executePipeline(workspace, action, teamConfig, { inspect, apiKey: "fake-key", signal: new AbortController().signal, python: pipelinePython(), driver: file, emit() {} });
    assert.equal(result.status, "completed");
  }
});
test("API imports bind cases to their source without rewriting it", () => {
  const { root, project } = fixture();
  const upload = saveDatasetUpload(root, project, "source.json", Buffer.from(JSON.stringify([{ id: "source-one", task: "Original task", solution: ["First solution", "Alternative"], errors: "Author error" }])));
  const action = parseApiPipelineAction({ stage: "generate", sourceId: pipelineSourceId(upload.path) });
  const before = readFileSync(upload.path, "utf8");
  const imports = preparePipelineDataset(root, project, action);
  assert.equal(imports[0].id, "Case001");
  assert.equal(imports[0].case.presentation, "Original task");
  assert.deepEqual(imports[0].case.source_provenance.supplied_solutions, ["First solution", "Alternative"]);
  assert.equal(imports[0].case.source_provenance.source_item_id, "source-one");
  writeFileSync(path.join(root, project, "cases", "Case001.json"), JSON.stringify(imports[0].case));
  assert.deepEqual(preparePipelineDataset(root, project, action), imports);
  assert.equal(readFileSync(upload.path, "utf8"), before);

  const item = { id: "Case002", source_item_id: "Case001", task: "Task", solutions: ["Solution"], errors: "" };
  saveDatasetDrafts(root, project, { revision: 0, selected: "new", drafts: { new: item }, bases: {} });
  const lineage = saveDatasetUpload(root, project, "lineage.json", Buffer.from(JSON.stringify(item)));
  for (const draftAction of [{ stage: "generate", draftKey: "new" }, { stage: "generate", sourceId: pipelineSourceId(lineage.path) }]) {
    const [record] = preparePipelineDataset(root, project, parseApiPipelineAction(draftAction));
    assert.equal(record.id, "Case002");
    assert.equal(record.case.source_provenance.source_item_id, "Case001");
  }
});
test("configuration API saves, refuses, and never launches execution", async () => {
  const { root, project } = fixture();
  createProject(root, "local-project", "", "local");
  const previousRoot = process.env.NOHARM_PROJECTS;
  const originalFetch = globalThis.fetch;
  process.env.NOHARM_PROJECTS = root;
  globalThis.fetch = (async url => {
    assert.equal(String(url), "https://openrouter.ai/api/v1/models");
    return Response.json({ data: catalog.data.map(model => ({ ...model, reasoning: { supported_efforts: ["low", "high"], mandatory: false } })) });
  }) as typeof fetch;
  const request = (value: unknown, name = project, origin = "http://localhost"): NextRequest => new NextRequest("http://localhost/api/pipeline/config", { method: "POST", headers: { origin, "Content-Type": "application/json" }, body: JSON.stringify({ project: name, config: value }) });
  try {
    assert.equal((await saveConfig(request(config))).status, 200);
    assert.deepEqual(loadApiPipelineConfig(root, project), config);
    assert.equal(existsSync(path.join(root, project, "web-execution")), false);
    assert.equal((await saveConfig(request(config, "local-project"))).status, 400);
    assert.equal((await saveConfig(request(config, project, "https://other.example"))).status, 403);
    const localRun = await runApi(new NextRequest("http://localhost/api/pipeline/run", { method: "POST", headers: { origin: "http://localhost", "Content-Type": "application/json" }, body: JSON.stringify({ project: "local-project", action: { stage: "responses" } }) }));
    assert.equal(localRun.status, 400);
    assert.match((await localRun.json()).error, /Local Mode/);

    assert.equal((await saveConfig(request(teamConfig))).status, 200);
    assert.deepEqual(loadApiPipelineConfig(root, project), teamConfig);
    assert.equal(existsSync(path.join(root, project, "web-execution")), false);
    const before = readFileSync(path.join(root, project, "api-pipeline.json"), "utf8");
    const unsupported = structuredClone(teamConfig);
    unsupported.teams.generation.integratorReasoning = { "fixture/writer": "max" };
    assert.equal((await saveConfig(request(unsupported))).status, 400);
    assert.equal(readFileSync(path.join(root, project, "api-pipeline.json"), "utf8"), before);
    const execution = path.join(root, project, "web-execution");
    mkdirSync(execution);
    writeFileSync(path.join(execution, "latest.json"), JSON.stringify({ status: "running" }));
    const blocked = await saveConfig(request(config));
    assert.equal(blocked.status, 409);
    assert.match((await blocked.json()).error, /resolve the current pipeline run/);
    assert.equal(readFileSync(path.join(root, project, "api-pipeline.json"), "utf8"), before);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousRoot === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = previousRoot;
  }
});
test("isolated execution publishes checkpoints before ACK and completes with saved results", async () => {
  const { root, project } = fixture();
  const workspace = localPipelineWorkspace(root, project);
  const events: PipelineEvent[] = [];
  const result = await executePipeline(workspace, { stage: "responses" }, config, { inspect, apiKey: "fake-key", signal: new AbortController().signal, python: pipelinePython(), driver: driver(workspace.root), emit(event) {
    events.push(event);
    if (event.type === "checkpoint") assert.deepEqual(JSON.parse(readFileSync(path.join(root, project, "results", "checkpoint.json"), "utf8")), { saved: true });
  } });
  assert.equal(result.status, "completed");
  assert.equal(existsSync(path.join(root, project, "results", "after-ack.json")), true);
  assert.equal(currentPipelineRun(path.join(root, project))?.status, "completed");
  assert.deepEqual(events.filter(event => event.type !== "progress").map(event => event.type), ["started", "checkpoint", "result"]);
});

const INTERRUPTIONS: { label: string; abortAtCheckpoint: boolean; files: Record<string, boolean> }[] = [
  { label: "abort before start", abortAtCheckpoint: false, files: { "checkpoint.json": false } },
  { label: "abort at checkpoint keeps the acknowledged receipt", abortAtCheckpoint: true, files: { "checkpoint.json": true, "after-ack.json": false } },
];

test("interruption never makes the next model call", () => eachCase(INTERRUPTIONS, (c) => c.label, async (c) => {
  const { root, project } = fixture();
  const workspace = localPipelineWorkspace(root, project);
  const controller = new AbortController();
  if (!c.abortAtCheckpoint) controller.abort();
  const result = await executePipeline(workspace, { stage: "responses" }, config, { inspect, apiKey: "fake-key", signal: controller.signal, driver: driver(workspace.root), emit(event) { if (c.abortAtCheckpoint && event.type === "checkpoint") controller.abort(); } });
  assert.equal(result.status, "interrupted");
  for (const [name, exists] of Object.entries(c.files)) assert.equal(existsSync(path.join(root, project, "results", name)), exists, name);
}));

test("a scoped stop waits for the in-flight output to checkpoint and prevents the next call", async () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "pipeline-stop-"));
  createProject(root, "stop-example", "", "api");
  const workspace = localPipelineWorkspace(root, "stop-example");
  const config: ApiPipelineConfig = { version: 1, generationModel: "fixture/writer", ratingModels: [], responseModels: ["fixture/model"], judgeModel: "fixture/judge" };
  const file = path.join(root, "stop-driver.py");
  writeFileSync(file, `import json, sys, time\nfrom pathlib import Path\nr=json.loads(sys.stdin.readline())\np=Path(r['project'])\n(p/'results').mkdir(exist_ok=True)\nprint('Current fixture call started',file=sys.stderr,flush=True)\ntime.sleep(0.05)\n(p/'results'/'current-call.json').write_text('{"saved":true}')\nprint(json.dumps({'type':'checkpoint','stage':'responses'}),flush=True)\nsys.stdin.readline()\n(p/'results'/'next-call.json').write_text('{}')\nprint(json.dumps({'type':'result','status':'completed'}),flush=True)\n`);
  const events: PipelineEvent[] = [];
  let requested = false;
  const result = await executePipeline(workspace, { stage: "responses" }, config, {
    apiKey: "fixture", signal: new AbortController().signal, python: pipelinePython(), driver: file,
    inspect: async () => ({ status: "ready", operationIdentity: "stop-fixture", reusableCalls: 0 }),
    emit(event) {
      events.push(event);
      if (event.type === "progress" && !requested) {
        requested = true;
        const job = currentPipelineRun(path.join(root, "stop-example"), workspace.key)!;
        assert.throws(() => stopPipelineRun("local:another-project", job.jobId), /no longer active/);
        assert.throws(() => stopPipelineRun(workspace.key, "another-job"), /no longer active/);
        assert.equal(currentPipelineRun(path.join(root, "stop-example"), workspace.key)?.stopping, undefined);
        assert.equal(stopPipelineRun(workspace.key, job.jobId).stopping, true);
        assert.equal(pipelineActive(workspace.key), true);
      }
    },
  });
  assert.equal(requested, true);
  assert.equal(result.status, "interrupted");
  assert.equal(result.stopping, false);
  assert.match(result.message, /Stopped after saving/);
  assert.deepEqual(JSON.parse(readFileSync(path.join(root, "stop-example", "results", "current-call.json"), "utf8")), { saved: true });
  assert.equal(existsSync(path.join(root, "stop-example", "results", "next-call.json")), false);
  assert.equal(events.some(event => event.stopping === true), true);
  assert.equal(events.at(-1)?.status, "interrupted");
  assert.equal(pipelineActive(workspace.key), false);
  assert.throws(() => stopPipelineRun(workspace.key, result.jobId), /no longer active/);
});

test("concurrent edits retain generated output separately and do not permit an unresolved rerun", async () => {
  const { root, project } = fixture();
  const workspace = localPipelineWorkspace(root, project);
  const source = path.join(root, project, "provenance.json");
  const result = await executePipeline(workspace, { stage: "responses" }, config, { inspect, apiKey: "fake-key", signal: new AbortController().signal, driver: driver(workspace.root), emit(event) {
    if (event.type === "started") writeFileSync(source, JSON.stringify({ ...JSON.parse(readFileSync(source, "utf8")), user_edit: "preserved" }));
  } });
  assert.equal(result.status, "failed");
  assert.match(result.error!, /changed during execution/);
  assert.equal(JSON.parse(readFileSync(source, "utf8")).user_edit, "preserved");
  assert.equal(existsSync(path.join(workspace.directory, "results", "checkpoint.json")), true);
  assert.equal(existsSync(path.join(workspace.directory, "results", "after-ack.json")), false);
  const retry = localPipelineWorkspace(root, project);
  await assert.rejects(executePipeline(retry, { stage: "responses" }, config, { inspect, apiKey: "fake-key", signal: new AbortController().signal, driver: driver(retry.root), emit() {} }), /unresolved final status/);
});

test("partial rescoring runs in Local Mode without a saved config and sends no config", async () => {
  const { root } = fixture();
  createProject(root, "local-project", "", "local");
  const previousRoot = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = root;
  const post = (project: string, action: Record<string, unknown>): Promise<Response> => runApi(new NextRequest("http://localhost/api/pipeline/run", { method: "POST", headers: { origin: "http://localhost", "Content-Type": "application/json" }, body: JSON.stringify({ project, action }) }));
  try {
    const partial = await post("local-project", { stage: "score", allowPartial: true });
    assert.equal(partial.status, 200);
    await partial.text();
    const refused = await post("local-project", { stage: "responses" });
    assert.equal(refused.status, 400);
    assert.match((await refused.json()).error, /Local Mode/);
  } finally {
    if (previousRoot === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = previousRoot;
  }
  const workspace = localPipelineWorkspace(root, "example");
  const file = path.join(workspace.root, "partial-driver.py");
  writeFileSync(file, "import json, sys\nr=json.loads(sys.stdin.readline())\nassert r['action']=={'stage':'score','allowPartial':True} and 'config' not in r\nprint(json.dumps({'type':'result','status':'completed','errors':[],'gaps':['model-a: no judgment for Case001']}),flush=True)\n");
  const result = await executePipeline(workspace, { stage: "score", allowPartial: true }, config, { inspect, apiKey: "", signal: new AbortController().signal, python: pipelinePython(), driver: file, emit() {} });
  assert.equal(result.status, "completed");
  assert.deepEqual(result.gaps, ["model-a: no judgment for Case001"]);
  assert.match(result.message, /1 coverage gap remains: model-a: no judgment for Case001/);
});

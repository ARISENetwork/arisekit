import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { createRequire } from "node:module";
import ts from "typescript";
import { saveRubricBeforeLeaving } from "../lib/rubric-editor-guard";

const require = createRequire(import.meta.url);
const cssLoader = require.extensions[".css"];
require.extensions[".css"] = module => { module.exports = {}; };
const { textV2Host }: typeof import("../components/TextV2RubricEditor") = require("../components/TextV2RubricEditor");
if (cssLoader) require.extensions[".css"] = cssLoader;
else delete require.extensions[".css"];

type Format = "legacy" | "text-v2";
interface Record { usualCare: { harm: string } }
interface Loaded { record: Record; sourceSha256: string; replacesSha256: string | null; canSave?: boolean }
interface State { loaded: Loaded; dirty: boolean; saving: boolean; status: string; message: string; refreshes: number }
interface Request {
  body: Loaded & { replacesSha256: string | null };
  resolve: (response: { version?: string; contentSha256?: string; message?: string }) => void;
  reject: (error: Error) => void;
}
interface Controls { canSave: boolean; saving: boolean; edit: (harm: string) => void; save: () => Promise<boolean> }

function editorHarness(format: Format, fileStorage = false): { state: State; requests: Request[]; render: () => Controls; finish: (index?: number) => void } {
  // The text rubric editor is noharm-science's (app/harmreview), driven through the toolkit's host.
  const [path, component_] = format === "legacy" ? ["../components/AnswerTableEditor.tsx", "AnswerTableEditorView"] : ["../harmreview/components/RubricEditor.tsx", "RubricEditor"];
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const component = file.statements.find((node): node is ts.FunctionDeclaration => ts.isFunctionDeclaration(node) && node.name?.text === component_);
  assert.ok(component?.body);
  const names = format === "legacy" ? ["markDirty", "updateUsualCare", "canSave", "save"] : ["updateV2", "save", "canSave"];
  const handlers = names.map((name) => {
    const statement = component.body!.statements.find((node) => ts.isVariableStatement(node) && node.declarationList.declarations.some((declaration) => ts.isIdentifier(declaration.name) && declaration.name.text === name));
    assert.ok(statement, `Missing ${name} handler`);
    return statement.getText(file);
  }).join("\n");
  const state: State = { loaded: { record: { usualCare: { harm: "mild" } }, sourceSha256: "source", replacesSha256: null }, dirty: true, saving: false, status: "dirty", message: "Unsaved changes", refreshes: 0 };
  const requests: Request[] = [];
  const storage = {
    reviewerId: "synthetic",
    onSaved: (): void => { state.refreshes += 1; },
    save: (request: Request["body"]): Promise<unknown> => new Promise((resolve, reject) => { requests.push({ body: JSON.parse(JSON.stringify(request)), resolve, reject }); }),
  };
  // Run the actual editor handlers with controlled network completion and render snapshots.
  const script = `() => {
    const { loaded, dirty, saving, status } = state;
    const v2 = loaded;
    const reviewerId = "synthetic", caseId = "Synthetic", endpoint = "/fake";
    const source = { caseset: "synthetic", version: "run1" };
    const previewOnly = false, errors = [], check = { errors: [] }, v2Check = { errors: [] };
    ${handlers}
    return { canSave, saving, save, edit: (harm: string) => ${format === "legacy" ? "updateUsualCare({ harm })" : "updateV2(\"D0\", (record) => ({ ...record, usualCare: { harm } }))"} };
  }`;
  const render = runInNewContext(ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, {
    state,
    savePending: { current: false },
    editRevision: { current: 0 },
    revision: { current: 0 },
    timing: { current: {} },
    useCallback: (callback: unknown): unknown => callback,
    setLoaded: (update: (current: Loaded) => Loaded): void => { state.loaded = update(state.loaded); },
    setV2: (update: (current: Loaded) => Loaded): void => { state.loaded = update(state.loaded); },
    setStatus: (status: string): void => { state.status = status; },
    setDirty: (dirty: boolean): void => { state.dirty = dirty; },
    setSaving: (saving: boolean): void => { state.saving = saving; },
    setMessage: (message: string): void => { state.message = message; },
    savedNotice: (version: string): string => version,
    recordEdit: (timing: unknown): unknown => timing,
    storage,
    host: textV2Host(storage as never, { current: { source: { caseset: "synthetic", version: "run1" }, synthetic: false, validationProvenance: {} } }),
  }) as () => Controls;
  return { state, requests, render, finish: (index = 0): void => requests[index].resolve(fileStorage ? { message: "Review downloaded." } : { version: "reviewed-test", contentSha256: `saved-${index}` }) };
}

for (const format of ["legacy", "text-v2"] as const) {
  test(`${format}: save-and-continue waits for the current revision`, async () => {
    const h = editorHarness(format);
    const controls = h.render();
    const saving = saveRubricBeforeLeaving({ ...controls, dirty: true, error: null });
    assert.equal(h.state.saving, true);
    h.finish();
    assert.equal(await saving, true);
    assert.equal(h.state.saving, false);
    assert.equal(h.state.dirty, false);
    assert.equal(h.state.status, "saved");
    assert.equal(h.state.refreshes, 1);
  });

  test(`${format}: newer edits remain unsaved and cannot close or overlap the pending save`, async () => {
    const h = editorHarness(format);
    const controls = h.render();
    const saving = saveRubricBeforeLeaving({ ...controls, dirty: true, error: null });
    h.render().edit("moderate");
    assert.equal(h.render().saving, true);
    assert.equal(h.render().canSave, false);
    assert.equal(await controls.save(), false);
    assert.equal(await h.render().save(), false);
    assert.equal(h.requests.length, 1);
    h.finish();
    assert.equal(await saving, false);
    assert.equal(h.requests[0].body.record.usualCare.harm, "mild");
    assert.equal(h.state.loaded.record.usualCare.harm, "moderate");
    assert.equal(h.state.dirty, true);
    assert.equal(h.state.status, "dirty");
    assert.equal(h.state.saving, false);
    assert.match(h.state.message, format === "legacy" ? /Newer edits remain unsaved/ : /^Unsaved changes$/);
    assert.equal(h.state.refreshes, 0, "refresh could select the new reviewer copy and remount the editor");

    const latest = h.render();
    assert.equal(latest.canSave, true);
    const next = saveRubricBeforeLeaving({ ...latest, dirty: h.state.dirty, error: null });
    assert.equal(h.requests[1].body.record.usualCare.harm, "moderate");
    assert.equal(h.requests[1].body.replacesSha256, "saved-0");
    h.finish(1);
    assert.equal(await next, true);
    assert.equal(h.state.dirty, false);
    assert.equal(h.state.refreshes, 1);
  });

  test(`${format}: file storage without a server version preserves newer edits until downloaded again`, async () => {
    const h = editorHarness(format, true);
    const pending = h.render().save();
    h.render().edit("severe");
    h.finish();
    assert.equal(await pending, false);
    assert.equal(h.state.dirty, true);
    assert.equal(h.state.loaded.record.usualCare.harm, "severe");
    assert.equal(h.state.loaded.sourceSha256, "source");
    assert.equal(h.state.loaded.replacesSha256, null);
    assert.equal(h.state.refreshes, 0);
    const latest = h.render().save();
    h.finish(1);
    assert.equal(await latest, true);
    assert.equal(h.state.dirty, false);
    assert.equal(h.state.message, "Review downloaded.");
  });

  test(`${format}: a failed save preserves newer edits and releases the save lock`, async () => {
    const h = editorHarness(format);
    const saving = h.render().save();
    h.render().edit("severe");
    h.requests[0].reject(new Error("Connection lost"));
    assert.equal(await saving, false);
    assert.equal(h.state.loaded.record.usualCare.harm, "severe");
    assert.equal(h.state.dirty, true);
    assert.equal(h.state.saving, false);
    assert.equal(h.render().canSave, true);
    assert.match(h.state.message, /Connection lost/);
  });
}

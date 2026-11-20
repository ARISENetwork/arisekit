import assert from "node:assert/strict";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { NextRequest } from "next/server";
import { GET, POST } from "../app/api/runs/expert-review/route";
import type { AnswerTableCase } from "../lib/answer-table";
import { newTiming, recordEdit } from "../lib/answer-table";
import { createProjectReviewPacket, createReviewPacket, importPortableReview, planReviewImport } from "../lib/caseset/portable-review";
import { loadTableVersion } from "../lib/caseset/read";
import { readReviews } from "../lib/caseset/reviews";
import { isValidReviewerId } from "../lib/clinician-review";
import { buildPortableHtml } from "../lib/portable-build";
import { parsePortableProgress, parsePortableReviewFile } from "../lib/portable-html";
import { expandPortableReviews, parsePortableReview, parseProjectReview, type PortableProjectReview, type PortableReview } from "../lib/portable-review";
import { buildFixture, CASESET, TABLE, writeCasesetFile } from "./caseset-fixture";
import { eachCase } from "./cases";

function submission(fixture: ReturnType<typeof buildFixture>, reviewer = "expert-one"): PortableReview {
  const packet = createReviewPacket(fixture.root, CASESET, "Test002", "run1");
  return { format: "noharm-expert-review-v1", packet, reviewer, record: structuredClone(TABLE),
    timing: newTiming(new Date("2026-10-19T12:00:00Z")), savedAt: "2026-10-19T12:15:00Z" };
}

function projectSubmission(): { fixture: ReturnType<typeof buildFixture>; review: PortableProjectReview } {
  const fixture = buildFixture();
  writeCasesetFile(fixture, "cases/Test003.json", { presentation: "Synthetic second task.", recommendations: "Synthetic second solution." });
  writeCasesetFile(fixture, "answer-tables/Test003.run1.json", { ...TABLE, caseId: "Test003" });
  writeCasesetFile(fixture, "answer-tables/Test003.run1.status.json", { status: "pass", errors: [] });
  const packet = createProjectReviewPacket(fixture.root, CASESET, "run1");
  const reviews = packet.packets.map((packet): PortableReview => ({ format: "noharm-expert-review-v1", packet, reviewer: "expert-one", record: structuredClone(packet.record), timing: newTiming(new Date("2026-10-19T12:00:00Z")), savedAt: "2026-10-19T12:15:00Z" }));
  return { fixture, review: { format: "noharm-project-expert-review-v1", packet, reviewer: "expert-one", reviews, savedAt: "2026-10-19T12:15:00Z" } };
}

test("exports render from the built shell without source files or build dependencies, embed the complete editor, and escape source markup", async () => {
  const runtime = mkdtempSync(path.join(tmpdir(), "portable-runtime-"));
  mkdirSync(path.join(runtime, "portable"));
  copyFileSync(path.join(process.cwd(), "portable/editor-shell.json"), path.join(runtime, "portable/editor-shell.json"));
  const html = await buildPortableHtml(submission(buildFixture()).packet, runtime);
  assert.match(html, /Expert Rubric Review/);
  assert.match(html, /Test002/);
  assert.match(html, new RegExp(readFileSync(path.resolve(process.cwd(), "../../../VERSION"), "utf8").trim().replaceAll(".", "\\.")));
  assert.equal(existsSync(path.join(runtime, "node_modules")), false);
  const f = buildFixture();
  const packet = createReviewPacket(f.root, CASESET, "Test002", "run1");
  packet.source.presentation = '</script><script>alert("source")</script>';
  const escaped = await buildPortableHtml(packet);
  assert.match(escaped, /Download Review/);
  assert.match(escaped, /connect-src 'none'/);
  assert.doesNotMatch(escaped, /<script[^>]+src=|<link[^>]+href=/i);
  const data = /<script id="review-packet" type="application\/json">([\s\S]*?)<\/script>/.exec(escaped)?.[1];
  assert.ok(data);
  assert.deepEqual(JSON.parse(data), packet);
  assert.doesNotMatch(data, /<script/);
});

test("a project export includes each case exactly once at the explicit version and never skips missing or failed rubrics", () => {
  const { fixture, review } = projectSubmission();
  assert.deepEqual(review.packet.packets.map((packet) => [packet.caseId, packet.version]), [["Test002", "run1"], ["Test003", "run1"]]);
  assert.throws(() => createProjectReviewPacket(fixture.root, CASESET, "run3"), /Test003.*No cases were skipped/);
  writeCasesetFile(fixture, "answer-tables/Test003.run1.status.json", { status: "failed", errors: ["invalid"] });
  assert.throws(() => createProjectReviewPacket(fixture.root, CASESET, "run1"), /Test003.*passes validation/);
});

test("project checkpoints can resume, but incomplete, duplicate, foreign, and mixed-reviewer submissions cannot import", () => {
  const { review } = projectSubmission();
  const partial = structuredClone(review);
  partial.reviews.pop();
  assert.equal(parseProjectReview(partial).reviews.length, 1);
  assert.throws(() => expandPortableReviews(partial), /incomplete: 1 of 2/);
  assert.equal(expandPortableReviews(review).length, 2);
  const duplicate = structuredClone(review); duplicate.reviews[1] = duplicate.reviews[0];
  assert.throws(() => expandPortableReviews(duplicate), /duplicate/);
  const mixed = structuredClone(review); mixed.reviews[1].reviewer = "another-expert";
  assert.throws(() => expandPortableReviews(mixed), /mismatched expert/);
  const foreign = structuredClone(review); foreign.reviews[1].packet.project = "other-project";
  assert.throws(() => expandPortableReviews(foreign), /mismatched/);
  const missingId = structuredClone(review); delete (missingId as Partial<PortableProjectReview>).reviewer;
  assert.throws(() => expandPortableReviews(missingId), /reviewer ID/);
  const duplicateManifest = structuredClone(review); duplicateManifest.packet.packets.push(duplicateManifest.packet.packets[0]);
  assert.throws(() => expandPortableReviews(duplicateManifest), /duplicate or mismatched cases/);
});

test("one project file previews and imports every expert copy, retains the whole submission, and remains idempotent", async (t) => {
  const { fixture: f, review } = projectSubmission();
  const previousRoot = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = f.root;
  t.after(() => { if (previousRoot === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = previousRoot; });
  const request = (values: unknown[], preview: boolean): NextRequest => new NextRequest("http://localhost:9017/api/runs/expert-review", {
    method: "POST", headers: { origin: "http://localhost:9017", "Content-Type": "application/json" }, body: JSON.stringify({ project: CASESET, reviews: values, preview }),
  });
  const exported = await GET(new NextRequest("http://localhost:9017/api/runs/expert-review?project=cs1&version=run1&scope=project"));
  assert.equal(exported.status, 200);
  assert.match(exported.headers.get("content-disposition") ?? "", /cs1.run1.expert-review.html/);
  const html = await exported.text();
  assert.match(html, /Test003/);
  assert.match(html, /Download Review/);
  const returnedHtml = await buildPortableHtml(review.packet, process.cwd(), { review, caseId: "Test003" });
  const returned = parsePortableReviewFile(returnedHtml);
  const preview = await POST(request([returned], true));
  assert.equal(preview.status, 200);
  assert.equal((await preview.json()).results.length, 2);
  assert.equal(existsSync(path.join(f.dir, "expert-reviews")), false);
  const partial = structuredClone(review); partial.reviews.pop();
  assert.equal((await POST(request([partial], false))).status, 400);
  const invalid = structuredClone(review); invalid.reviews[1].packet.sourceSha256 = "0".repeat(64); invalid.packet.packets[1].sourceSha256 = "0".repeat(64);
  assert.equal((await POST(request([invalid], false))).status, 400);
  assert.equal(existsSync(path.join(f.dir, "expert-reviews")), false, "invalid second case prevents the first import");
  const invalidTiming = structuredClone(review); invalidTiming.reviews[1].timing = {} as PortableReview["timing"];
  assert.equal((await POST(request([invalidTiming], false))).status, 400);
  assert.equal(existsSync(path.join(f.dir, "expert-reviews")), false, "invalid second-case history prevents the first import");
  assert.equal((await POST(request([review, review.reviews[0]], false))).status, 400);
  assert.equal((await POST(request([returned], false))).status, 200);
  const repeated = await POST(request([returned], false));
  assert.equal(repeated.status, 200);
  assert.deepEqual((await repeated.json()).results.map((item: { status: string }) => item.status), ["already imported", "already imported"]);
  for (const item of review.reviews) assert.deepEqual(loadTableVersion(f.dir, item.packet.caseId, "reviewed-expert-one").record, item.record);
  const receipts = readdirSync(path.join(f.dir, "expert-reviews"));
  assert.equal(receipts.length, 3);
  const original = receipts.find((name) => name.startsWith("project-"));
  assert.ok(original);
  assert.deepEqual(JSON.parse(readFileSync(path.join(f.dir, "expert-reviews", original), "utf8")), review);
  assert.equal(readReviews(f.dir).length, 2);
});

test("expert copies and original submissions remain separate, repeating an import adds nothing, and a changed copy is refused without replacing content or history", () => {
  const f = buildFixture();
  const original = readFileSync(path.join(f.dir, "answer-tables/Test002.run1.json"), "utf8");
  const first = submission(f);
  const second = submission(f, "expert-two");
  second.record.decisions[1].question = "Should anticoagulation be started?";
  assert.equal(planReviewImport(f.root, CASESET, first).status, "ready");
  assert.equal(existsSync(path.join(f.dir, "expert-reviews")), false, "preview writes nothing");
  importPortableReview(f.root, CASESET, first);
  importPortableReview(f.root, CASESET, second);
  assert.equal(importPortableReview(f.root, CASESET, first).status, "already imported");
  assert.deepEqual(loadTableVersion(f.dir, "Test002", "reviewed-expert-one").record, first.record);
  assert.deepEqual(loadTableVersion(f.dir, "Test002", "reviewed-expert-two").record, second.record);
  assert.equal(readFileSync(path.join(f.dir, "answer-tables/Test002.run1.json"), "utf8"), original);
  const receipts = readdirSync(path.join(f.dir, "expert-reviews"));
  assert.equal(receipts.length, 2);
  assert.deepEqual(new Set(receipts.map((name) => JSON.parse(readFileSync(path.join(f.dir, "expert-reviews", name), "utf8")).reviewer)), new Set(["expert-one", "expert-two"]));
  assert.equal(readReviews(f.dir).length, 2);
  const conflicted = buildFixture();
  const changed = submission(conflicted);
  importPortableReview(conflicted.root, CASESET, changed);
  changed.record.usualCare!.harm = "severe";
  assert.throws(() => importPortableReview(conflicted.root, CASESET, changed), /already exists with different content/);
  assert.equal(loadTableVersion(conflicted.dir, "Test002", "reviewed-expert-one").record?.usualCare.harm, "moderate");
  assert.equal(readdirSync(path.join(conflicted.dir, "expert-reviews")).length, 1);
  assert.equal(readReviews(conflicted.dir).length, 1);
});

test("full structural and wording edits retain the exact original rubric identity", () => {
  const f = buildFixture();
  const review = submission(f);
  review.record.decisions[1].question = "Should anticoagulation be started now?";
  (review.record as AnswerTableCase).decisions[0].recommendations.push({ id: "D1.O2", text: "Arrange outpatient cardiology follow-up.", score: 7, timing: "routine" });
  importPortableReview(f.root, CASESET, review);
  const saved = loadTableVersion(f.dir, "Test002", "reviewed-expert-one");
  assert.deepEqual(saved.record, review.record);
  assert.deepEqual(saved.basedOn, { version: "run1", sha256: review.packet.sourceSha256 });
  assert.equal(saved.savedAt, new Date(review.savedAt).toISOString());
});

test("wrong projects, changed rubrics, changed source text, and tampered packets cannot be imported", () => eachCase(["project", "rubric", "source", "packet"] as const, (kind) => kind, (kind) => {
  const f = buildFixture();
  const review = submission(f);
  if (kind === "project") review.packet.project = "another-project";
  if (kind === "rubric") writeCasesetFile(f, "answer-tables/Test002.run1.json", { ...TABLE, usualCare: { harm: "severe" } });
  if (kind === "source") writeCasesetFile(f, "cases/Test002.json", { presentation: "Changed task", recommendations: "Changed solution" });
  if (kind === "packet") review.packet.record.usualCare!.harm = "severe";
  assert.throws(() => importPortableReview(f.root, CASESET, review), /belongs to|changed after export|does not match/);
  assert.equal(existsSync(path.join(f.dir, "expert-reviews")), false);
  assert.equal(existsSync(path.join(f.dir, "answer-tables/Test002.reviewed-expert-one.json")), false);
}));

test("invalid rubrics and reviewer IDs cannot create an expert copy", () => {
  assert.ok(isValidReviewerId("dw"));
  assert.ok(isValidReviewerId("reviewer-2"));
  assert.ok(!isValidReviewerId("D"));
  assert.ok(!isValidReviewerId("Dr Wu"));
  assert.ok(!isValidReviewerId("../etc"));
  const f = buildFixture();
  assert.throws(() => createReviewPacket(f.root, CASESET, "Test002", "run2"), /passes validation/);
  const review = submission(f);
  review.reviewer = "../another";
  assert.throws(() => parsePortableReview(review), /Reviewer ID/);
  review.reviewer = "expert-one";
  review.record.usualCare!.harm = null;
  assert.throws(() => importPortableReview(f.root, CASESET, review), /harm/);
  assert.equal(existsSync(path.join(f.dir, "expert-reviews")), false);
});

test("malformed editing history is rejected before resuming or importing a review", async () => {
  const fixture = buildFixture();
  const review = submission(fixture);
  const valid = review.timing;
  const invalid: unknown[] = [
    {}, null, [],
    { ...valid, sessionStartedAt: "invalid" },
    { ...valid, lastInteractionAt: null },
    { ...valid, activeMs: "0" },
    { ...valid, activeMs: -1 },
    { ...valid, activeMs: NaN },
    { ...valid, activeMs: Infinity },
    { ...valid, editCount: -1 },
    { ...valid, editCount: 0.5 },
    { ...valid, decisions: null },
    { ...valid, decisions: [] },
    { ...valid, decisions: { D2: null } },
    { ...valid, decisions: { D2: {} } },
    { ...valid, decisions: { D2: { firstEditAt: valid.sessionStartedAt, lastEditAt: "invalid", editCount: 1 } } },
    { ...valid, decisions: { D2: { firstEditAt: valid.sessionStartedAt, lastEditAt: valid.lastInteractionAt, editCount: -1 } } },
  ];
  for (const timing of invalid) {
    const malformed = { ...review, timing };
    assert.throws(() => parsePortableReview(malformed), /editing history/);
    assert.throws(() => parsePortableProgress({ review: malformed, caseId: review.packet.caseId }, review.packet), /editing history/);
    assert.throws(() => importPortableReview(fixture.root, CASESET, malformed), /editing history/);
  }
  assert.equal(existsSync(path.join(fixture.dir, "expert-reviews")), false);
  const html = await buildPortableHtml(review.packet, process.cwd(), { review, caseId: review.packet.caseId });
  const corrupted = html.replace(/(<script id="review-progress" type="application\/json">)[\s\S]*?(<\/script>)/,
    (_match, open: string, close: string): string => `${open}${JSON.stringify({ review: { ...review, timing: {} }, caseId: review.packet.caseId }).replace(/</g, "\\u003c")}${close}`);
  assert.throws(() => parsePortableReviewFile(corrupted), /editing history/);
  const { review: project } = projectSubmission();
  project.reviews[1].timing = {} as PortableReview["timing"];
  assert.throws(() => parseProjectReview(project), /editing history/);
});

test("valid editing history survives a resumed edit, including history for deleted decisions", () => {
  const review = submission(buildFixture());
  const at = review.timing.sessionStartedAt;
  review.timing = { ...review.timing, activeMs: 500, editCount: 1,
    decisions: { D999: { firstEditAt: at, lastEditAt: at, editCount: 1 } } };
  const progress = parsePortableProgress({ review, caseId: review.packet.caseId }, review.packet);
  const resumed = progress.review;
  assert.ok(resumed.format === "noharm-expert-review-v1");
  assert.deepEqual(resumed.timing, review.timing);
  const timing = recordEdit(resumed.timing, "D2", new Date("2026-10-19T12:00:01Z"));
  assert.equal(timing.activeMs, 1500);
  assert.equal(timing.editCount, 2);
  assert.equal(timing.decisions.D2.editCount, 1);
  assert.deepEqual(timing.decisions.D999, review.timing.decisions.D999);
});

test("saved HTML carries edited content, identity, timing, and position without executing imported markup", async () => {
  const f = buildFixture();
  const review = submission(f);
  review.record.decisions[1].question = '</script><script>throw new Error("untrusted review")</script>';
  const progress = { review, caseId: review.packet.caseId };
  const html = await buildPortableHtml(review.packet, process.cwd(), progress);
  const data = /<script id="review-progress" type="application\/json">([\s\S]*?)<\/script>/.exec(html)?.[1];
  assert.ok(data);
  assert.doesNotMatch(data, /<script/);
  assert.deepEqual(parsePortableProgress(JSON.parse(data), review.packet), progress);
  assert.deepEqual(parsePortableReviewFile(`${html}<script>throw new Error("must not execute")</script>`), review);
  assert.deepEqual(parsePortableReviewFile(JSON.stringify(review)), review, "existing JSON submissions still import");
  assert.equal(planReviewImport(f.root, CASESET, parsePortableReviewFile(html)).status, "ready");
  importPortableReview(f.root, CASESET, parsePortableReviewFile(html));
  assert.deepEqual(loadTableVersion(f.dir, review.packet.caseId, "reviewed-expert-one").record, review.record);
  assert.equal(loadTableVersion(f.dir, review.packet.caseId, "run1").record?.decisions[1].question, TABLE.decisions[1].question);
});

test("project HTML can checkpoint partial progress, but incomplete files and mismatched resume state cannot import", async () => {
  const { review } = projectSubmission();
  const partial = structuredClone(review);
  partial.reviews.pop();
  const html = await buildPortableHtml(partial.packet, process.cwd(), { review: partial, caseId: "Test003" });
  const restored = parsePortableReviewFile(html);
  assert.deepEqual(restored, partial);
  assert.throws(() => expandPortableReviews(restored), /incomplete: 1 of 2/);
  assert.throws(() => parsePortableProgress({ review, caseId: "unassigned" }), /current case/);
  assert.throws(() => parsePortableProgress({ review, caseId: "Test003" }, { ...review.packet, project: "another-project" }), /different assignment/);
  assert.deepEqual(parsePortableReviewFile(JSON.stringify(review)), review);
  const fresh = await buildPortableHtml(review.packet);
  assert.throws(() => parsePortableReviewFile(fresh), /no saved review/);
});

test("the import endpoint previews a whole batch before writing, rejects duplicates, and enforces the site origin", async (t) => {
  const f = buildFixture();
  const previousRoot = process.env.NOHARM_PROJECTS;
  process.env.NOHARM_PROJECTS = f.root;
  t.after(() => { if (previousRoot === undefined) delete process.env.NOHARM_PROJECTS; else process.env.NOHARM_PROJECTS = previousRoot; });
  const reviews = [submission(f), submission(f, "expert-two")];
  const request = (values: unknown[], preview: boolean, origin = "http://localhost:9017"): NextRequest => new NextRequest("http://localhost:9017/api/runs/expert-review", {
    method: "POST", headers: { origin, "Content-Type": "application/json" },
    body: JSON.stringify({ project: CASESET, reviews: values, preview }),
  });
  const preview = await POST(request(reviews, true));
  assert.equal(preview.status, 200);
  assert.equal((await preview.json()).results.length, 2);
  assert.equal(existsSync(path.join(f.dir, "expert-reviews")), false);
  assert.equal((await POST(request([reviews[0], reviews[0]], false))).status, 400);
  const invalid = structuredClone(reviews[1]); invalid.packet.project = "wrong";
  assert.equal((await POST(request([reviews[0], invalid], false))).status, 400);
  assert.equal(existsSync(path.join(f.dir, "expert-reviews")), false, "one invalid review prevents the whole batch from starting");
  assert.equal((await POST(request(reviews, false, "http://another-site.test"))).status, 403);
  assert.equal((await POST(request(reviews, false))).status, 200);
  assert.equal(readdirSync(path.join(f.dir, "expert-reviews")).length, 2);
  assert.equal(readReviews(f.dir).length, 2);
});

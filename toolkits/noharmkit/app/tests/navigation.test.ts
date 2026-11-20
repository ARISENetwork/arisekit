import assert from "node:assert/strict";
import { test } from "node:test";

import type { NavData } from "../components/mc/nav";
import { STEP_KEYS } from "../lib/caseset/steps";
import { navigationMotion } from "../lib/navigation-motion";
import { localPath, noharmHref } from "../lib/noharm-path";
import { roadmapStops } from "../lib/roadmap";
import { eachCase } from "./cases";

function harness() {
  const transitions: Array<{ run: () => Promise<void>; skip: boolean; finish: () => void }> = [];
  const motion = navigationMotion((run) => {
    let finish!: () => void;
    const finished = new Promise<void>((resolve) => { finish = resolve; });
    const entry = { run, skip: false, finish };
    transitions.push(entry);
    return { ready: Promise.resolve(), finished, skipTransition: () => { entry.skip = true; finish(); } };
  });
  return { motion, transitions };
}

test("the snapshot waits for the intended route, including case query changes", async () => {
  const { motion, transitions } = harness();
  let navigated = false;
  let completed = false;
  motion.navigate("/cases?case=B", () => { navigated = true; });
  const run = transitions[0].run().then(() => { completed = true; });
  assert.equal(navigated, true);
  assert.equal(motion.commit("/cases?case=A"), false);
  await Promise.resolve();
  assert.equal(completed, false);
  assert.equal(motion.commit("/cases?case=B"), true);
  await run;
  transitions[0].finish();
  motion.cancel();
});

test("rapid navigation cancels a superseded callback before it can navigate", async () => {
  const { motion, transitions } = harness();
  const destinations: string[] = [];
  motion.navigate("/cases", () => { destinations.push("cases"); });
  motion.navigate("/leaderboard", () => { destinations.push("leaderboard"); });
  await transitions[0].run();
  assert.equal(transitions[0].skip, true);
  const run = transitions[1].run();
  motion.commit("/leaderboard");
  await run;
  assert.deepEqual(destinations, ["leaderboard"]);
  transitions[1].finish();
  motion.cancel();
});

test("cancellation releases a pending route and allows another transition", async () => {
  const { motion, transitions } = harness();
  motion.navigate("/rubrics", () => {});
  const run = transitions[0].run();
  motion.cancel();
  await run;
  assert.equal(transitions[0].skip, true);
  motion.navigate("/scores", () => {});
  const next = transitions[1].run();
  assert.equal(motion.commit("/scores"), true);
  await next;
  transitions[1].finish();
  motion.cancel();
});

test("a slow request releases its snapshot without preventing the eventual navigation", async () => {
  const { motion, transitions } = harness();
  let navigated = false;
  motion.navigate("/responses", () => { navigated = true; });
  await new Promise((resolve) => setTimeout(resolve, 2050));
  assert.equal(transitions[0].skip, true);
  await transitions[0].run();
  assert.equal(navigated, true);
  motion.cancel();
});

const PATH_CASES: { fn: "noharmHref" | "localPath"; input: string; expected: string | null }[] = [
  { fn: "noharmHref", input: "/rubrics?case=Test002", expected: "/noharm/rubrics?case=Test002" },
  { fn: "noharmHref", input: "guide", expected: "/noharm/guide" },
  { fn: "localPath", input: "/noharm", expected: "/" },
  { fn: "localPath", input: "/noharm/rubrics", expected: "/rubrics" },
  { fn: "localPath", input: "/noharmx/rubrics", expected: null },
  { fn: "localPath", input: "/rubrics", expected: null },
  { fn: "localPath", input: "/", expected: null },
];

test("noharm path prefix", () => eachCase(PATH_CASES, (c) => `${c.fn}(${c.input})`, (c) => {
  assert.equal(c.fn === "noharmHref" ? noharmHref(c.input) : localPath(c.input), c.expected);
}));

const nav = (benchmark: string): NavData => ({
  benchmark, benchmarks: benchmark ? [benchmark] : [], dev: false, updatedLabel: null,
  dots: Object.fromEntries(STEP_KEYS.map((k) => [k, k === "cases" ? "reviewed" : "none"])) as NavData["dots"],
});

test("roadmap stops, current step, and welcome dot", () => {
  const stops = roadmapStops(nav("demo"), "/rubrics", { case: "Test002" });
  assert.deepEqual(stops.map((s) => s.name), ["Welcome", "Dataset", "Rubrics", "Responses", "Autograding", "Scores", "Leaderboard"]);
  assert.equal(stops[0].href, "/noharm/welcome");
  assert.equal(stops[2].href, "/noharm/rubrics?case=Test002");
  assert.deepEqual(stops.filter((s) => s.current).map((s) => s.key), ["rubrics"]);
  assert.equal(roadmapStops(nav("demo"), "/welcome", {})[0].dot, "reviewed");
  assert.equal(roadmapStops(nav(""), "/welcome", {})[0].dot, "none");
  assert.equal(roadmapStops(nav("demo"), "/review", {}).find((s) => s.current)?.key, "rubrics");
  assert.equal(roadmapStops(nav("demo"), "/dashboard", {}).some((s) => s.current), false);
});

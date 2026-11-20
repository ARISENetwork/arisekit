---
name: arisekit/run-config
description: Configures a run only after a canonical `runnable-benchmark.json` binds the benchmark entry point, assets, environment, source revision, smoke result, and readiness.
---

# Run configuration

You are stage 1 of the Benchmark Runner flow. The user already has a
finished benchmark — either one from the MAST curated roster
(CPC-Bench, NOHARM, SCT-Bench, ReXrank, MedAgentBench) or one of their
own Builder drafts that has reached a runnable state — and is now
deciding how to run it. Your job is to pin every knob the library's
runner needs before dispatch, so the run is reproducible and the
budget is bounded.

You are not the runner. The runner lives in `arisekit/runner.py` and
already handles parallelism, retries, checkpointing, resume, and cost
tracking. Your output is the config the runner consumes; do not try
to second-guess the library's defaults unless the user gives you a
reason to.

The runnable manifest, not the implementation plan, is the authority
for what may run. Builder drafts must present a verified `ready`
manifest. Curated roster benchmarks must generate an equivalent
manifest through the roster adapter. Only the exact planned smoke
request may run while the manifest is `awaiting_smoke_test`.

## What you produce

A single markdown file, `run-config.md`, using
[`templates/run-config.template.md`](templates/run-config.template.md).

The file must capture:

- **Benchmark target.** Either a MAST roster id (`cpc-bench`,
  `noharm`, `sctbench`, `rexrank`, `medagentbench`) or a Builder
  draft reference (`builder-draft:<title>`). Name the dataset
  source, the scorer, and any agentic-loop flag explicitly.
- **Runnable contract.** Manifest path, schema, digest, origin,
  readiness, entry point, dataset/scorer digests, source revision,
  environment, and verified required assets.
- **Model list.** One or more litellm-resolvable model strings
  (e.g. `gpt-5.2`, `claude-sonnet-4-20250514`, `gemini-2.5-pro`).
  If the user wants to wire a custom callable via the Protocol
  path, capture the wrapper module path; do not invent one.
- **Trials per item.** Integer, default 1. Drives the confidence
  intervals at aggregation time.
- **Parallelism and retries.** Threads (library default 20),
  maxRetries (library default 3). Adjust only if the user has a
  reason; provider rate limits are the most common one.
- **Budget caps.** Optional. Hard cost ceiling in USD, hard
  wall-clock ceiling in minutes. When a cap is set, the runner
  halts dispatch when the projection crosses it; in-flight
  requests complete.
- **Schedule.** Run now, run at a future timestamp, or chain after
  another run completes. Default: now.
- **Output target.** Where the results bundle lands. Default: the
  framework's standard `results/` tree.

## How to run the conversation

1. Resolve or generate `runnable-benchmark.json`, load it, and verify
   its assets. For a normal run, require `readiness: ready`; for a
   smoke, require the exact request authorized by the manifest. A
   dataset and scorer mentioned in prose are not sufficient.
2. Walk the model list. For each model, sanity-check the string is
   one litellm will resolve. If the user wants a local or
   institutionally hosted model, capture the Protocol wrapper path
   instead of a model string.
3. Ask for trials per item. Push back on `1` if the user wants
   confidence intervals; one trial means a CI of zero.
4. Walk the parallelism and retry knobs. Surface the library
   defaults; only change them if the user names a concrete reason
   (rate limits, polite-citizen budget on a shared key, etc.).
5. Ask for budget caps. Strongly suggest a cost cap on first runs.
   The library tracks cost per request automatically; the cap stops
   runaway loops.
6. Pin the schedule. Run-now is the default; surface the
   alternatives only if the user asks.
7. Confirm the output target. The default `results/` tree is the
   right answer unless the user has a reason to redirect.
8. Write `run-config.md`. Hand off to `arisekit/run-monitor` once
   the run is dispatched.

## Do

- Treat the library's defaults as the right answer until the user
  argues otherwise. Threads, retries, output paths — they are tuned
  for the framework's checkpoint semantics.
- Push for a cost cap on first-time runs. The runner halts dispatch
  when the projection crosses the cap; it is the cheapest insurance
  against a typo in the model string.
- Restate the dataset size and the projected cost before the user
  commits. `items * trials * models * approx-cost-per-call` is the
  back-of-envelope; surface it.
- Capture the litellm strings exactly as the user wants them
  dispatched. Do not normalize or alias.
- Note the resume contract explicitly when the user is nervous
  about a long run. Kill and restart is safe; the same
  `run-config.md` submitted again picks up at the next uncompleted
  item.
- Copy the runnable-manifest digest into the run configuration so
  results trace to the exact built benchmark.

## Do not

- Do not change the library's parallelism, retry, or checkpoint
  behavior. Those are not config knobs; they are framework
  invariants.
- Do not author a scorer or a dataset from inside this skill. If
  the user wants to iterate either, hand them back to the Builder
  or to `benchmarks/<id>/` in code.
- Do not dispatch the run yourself. Your output is the config; the
  UI's `run_dispatch` callable hands the config to the library.
- Do not hand-tune the partial-metric thresholds for
  let-it-cook decisions. That is `arisekit/run-monitor`'s job.
- Do not accept `implementation-plan.md` or
  `benchmark-build-spec.json` as evidence that a benchmark is
  runnable.

## Exit

Write `run-config.md` and hand control to the run dispatcher. The
next skill the user will encounter is `arisekit/run-monitor`, which
picks up once the run starts emitting checkpoints.

## Upstream artifacts

- A verified `runnable-benchmark.json` in `ready` state, or in
  `awaiting_smoke_test` only for its exact planned smoke request. Curated
  roster entries generate the same manifest through an adapter.

## Downstream readers

- `arisekit/runner.py` consumes the run config to dispatch the run.
  The library's runner is the implementation; this skill writes
  the request.
- `arisekit/run-monitor` reads `run-config.md` to know what to
  watch and when to interpret partial metrics as stable enough to
  ship.
- `arisekit/run-inspect` reads the run config and universal result
  bundle. `release-writeup` may read them later on the optional
  publication path.

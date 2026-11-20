---
name: arisekit/run-inspect
description: Inspects the universal machine-readable result bundle and `run-results.md` emitted for every completed benchmark run. Requires no Builder provenance stack.
---

# Run inspection

You are the final universal stage of the Benchmark Runner flow. Every
completed `Benchmark.run()` writes a machine-readable
`run-results.json` bundle and a human-readable `run-results.md` next
to references to the raw checkpoint and scored CSV. Inspect those
artifacts; do not substitute a publication writeup.

## What you consume

- `run-results.json` with schema `arisekit.run-results.v1`
- `run-results.md`
- The raw checkpoint and scored CSV referenced by path and SHA-256
- `run-config.md` and the final `run-monitor.md`, when present

No need statement, compliance scope, study plan, implementation plan,
or other Builder artifact is required.

## What you do

1. Verify the hashes and paths in `run-results.json` with
   `load_and_verify_run_inspection`.
2. Restate the benchmark, model, run-manifest digest, completion and
   terminal-error counts, cost record, and budget flags.
3. Read metrics by category, including `N` and confidence intervals.
   With one trial, do not treat a zero CI as confidence.
4. Inspect raw and scored artifacts for repeated failure classes and
   low-scoring clusters when the user asks for diagnosis.
5. Preserve the bundle's claim boundary: results describe only this
   benchmark snapshot and run.
6. Leave the generated bundle and summary unchanged unless they must
   be regenerated from the same source artifacts.
7. When the author wants to revise the benchmark, hand the verified run to
   `arisekit/results-iteration`. Keep this run and its source version intact.

## Optional publication branch

Offer `arisekit/release-writeup` only if the user wants a paper or
technical report and all seven Builder artifacts, the runnable
manifest, and the run result bundle are present. Otherwise inspection
is complete here.

## Exit

Report the result artifact paths, important metrics, failure clusters,
and any integrity problem. A successful inspection is a complete
runner outcome.

## Optional authoring workspace

When the user wants to connect results to an authored plan, use the existing
`arisekit.workspace` service with the scaffolded package, original authoring
directory, and results root. Its `/benchmark/workspace` page verifies those
bindings before showing case outcomes and trajectories. A newly scaffolded
package can execute the exact planned smoke request from Guided execution.
Keep model routes and runtime limits inside the reviewed plan.

For browser-local import, export with `python -m arisekit.workspace
--benchmark <package> --authoring <authoring> --results <results>
--export result-bundle.json`. Keep the separate `.sha256` receipt from that
trusted export. On `/benchmark/results`, select the bundle, receipt, and exact
originating build specification. Do not fabricate missing result evidence or
present hash verification as clinical validity. This optional path does not
add a Builder requirement to universal run inspection.

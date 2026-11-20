---
name: arisekit/target-stress-design
description: Designs a target-specific benchmark from validated residual failure evidence without touching sealed validation outcomes. Use when a benchmark operator wants to exploit a pinned model snapshot's weak point. Produces `target-stress-plan.md` and `stress-spec.json`.
---

# Target stress design

Design one frozen target-specific stress benchmark. Discovery may identify a
failure; sealed validation decides whether the benchmark earned its claim.

## What you produce

Write `target-stress-plan.md` with the template, then serialize the frozen
`arisekit.analysis.stress.StressBenchmarkSpec` as `stress-spec.json`.

## Conversation

1. Pin the target model name, family, provider snapshot, and date. Pin an
   acquisition panel whose canonical member digest matches the declared panel
   hash, and exclude the target lineage.
2. Freeze distinct discovery, calibration, and sealed-validation cohorts. Bind
   exact cohort membership hashes. Acquisition may use only discovery and
   calibration.
3. Require typed residual-signal evidence: difficulty-and-ability baseline,
   residual analysis, permutation null, and heldout confirmation. Reject a
   failure signal explained only by global item difficulty or model ability.
4. Freeze selected item features and the approved control pool, then call
   `arisekit.match_stress_cohorts`. Record selected/control hashes and counts,
   exact assignments and distances, calipers, reuse, disjointness, source
   matching, case matching, and balance diagnostics. If deterministic matching
   cannot satisfy every frozen caliper and reuse limit, stop rather than hand-
   editing assignments.
5. Pin prompts, rubrics, executable judge panel members/config, code, and source
   revision.
6. Preregister the validation decision rule: metric, direction, estimand,
   minimum difficulty-matched target lift, minimum cross-panel specificity,
   invalidity bounds for each, confidence level, sample-size floor, and
   multiplicity correction.
7. Write the artifacts. Do not open sealed outcomes or assert a verdict.

## Do not

- Do not use the sealed cohort for acquisition, prompt edits, or threshold
  selection.
- Do not call this a general capability benchmark.
- Do not accept caller-written `validated` state.
- Do not use target-family models in the acquisition or judge panels.

## Downstream readers

- `arisekit/target-stress-validation` consumes the frozen spec once.
- `arisekit.package.write_package` preserves `stress-spec.json`.

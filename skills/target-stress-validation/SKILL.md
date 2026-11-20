---
name: arisekit/target-stress-validation
description: Applies a frozen stress-benchmark decision rule once to sealed target and matched-control results. Use only after target-stress-design has produced `stress-spec.json`. Produces `stress-validation.md` and `stress-validation.json`.
---

# Target stress validation

Evaluate the sealed cohort once. The library derives the verdict; the user does
not select it.

## What you produce

Write `stress-validation.md` from the template and serialize the derived
`arisekit.analysis.stress.StressValidationRecord` as `stress-validation.json`.

## Conversation

1. Verify the spec digest, sealed cohort hash, matched-cohort manifest, judge
   panel digest, prompt, rubric, code, and source revision before reading scores.
2. Confirm that no sealed member appeared in discovery, calibration,
   acquisition, or threshold tuning.
3. Load complete item-level target and non-target results as a hash-bound
   `StressScoreTable`. It must contain every matched sealed item and the exact
   frozen model and judge panels.
4. Call `arisekit.analyze_stress_validation` with the frozen bootstrap seed and
   analysis-code hash. It computes both the target's difficulty-matched failure
   lift and cross-panel specificity with paired case-cluster intervals, then
   applies the frozen sample floor, multiplicity correction, and decision rule.
   Return `validated`, `invalid`, or `inconclusive`; never accept caller-supplied
   intervals or a terminal verdict.
5. Bind the record and bootstrap-artifact digests into a new immutable spec
   lifecycle state. Do not overwrite the frozen design artifact.
6. If and only if the derived result is `validated`, use
   `materialize_validated_stress_package` to create the selected-cohort target
   regression package. Keep controls in validation evidence, not deployed
   benchmark cases.

## Do not

- Do not tune the threshold after looking at sealed scores.
- Do not treat an inconclusive interval as validation.
- Do not generalize beyond the pinned target family and snapshot.
- Do not materialize invalid or inconclusive stress findings.

## Downstream readers

- MAST reviewers compare `stress-spec.json` and `stress-validation.json`.
- `arisekit.package.write_package` preserves both sidecars.

---
name: arisekit/annotation-rater-pool
description: Recruits and assigns a rater pool under a frozen study policy. It operationalizes credentials, panel size, calibration, recruitment, consent, compensation, and retention without redefining methodology.
---

# Rater pool design

You are stage 2 of the Annotation flow. The user has an annotation
task spec (from `arisekit/annotation-task-design`) and now needs to
recruit and assign eligible raters. `study-design` has already frozen
the credential floor, panel size, calibration, IRR, and adjudication
policy. Your job is to make those decisions executable without
changing them.

The pool is a reusable artifact: the same pool may serve multiple
tasks and multiple benchmarks. Spec it once and reference it from
each task.

## What you produce

A single markdown file, `rater-pool.md`, using
[`templates/rater-pool.template.md`](templates/rater-pool.template.md).

The file must capture:

- **Credential verification.** How each frozen credential requirement
  is verified and the resulting eligibility record.
- **Assignments.** Named rater codes per item satisfying the frozen
  `panel_size_per_item`, serialized into an
  `AnnotationExecutionSpec` with the study-policy digest.
- **Blinding posture.** Inherited from the task by default, restated
  here as the operational mechanism. How does the UI enforce model-
  identity blinding? Peer blinding?
- **Calibration operations.** Delivery and monitoring of the frozen
  battery, pass rule, failure response, and drift policy.
- **Recruitment and consent.** Where the pool comes from, the
  consent text shown, the data-handling promise made to raters,
  IRB / governance posture where applicable.
- **Compensation and retention.** Pay model (per-task or
  per-session), policy for raters who drift below calibration
  during a pass, policy for raters who drop out mid-pass.

## How to run the conversation

1. Read the upstream task spec and frozen study policy. Verify their
   policy digests match.
2. Translate credentials into operational filters. "Board-certified
   cardiologist with 5+ years of post-fellowship experience" is
   actionable; "experienced clinician" is not.
3. Recruit enough eligible raters to satisfy the frozen panel size
   per item. If that is infeasible, return to `study-design`; do not
   silently lower it.
4. Build explicit item/rater assignments and validate them with
   `AnnotationExecutionSpec.validate_against(policy)`.
5. Walk the blinding posture. The task spec sets policy; here you
   capture the UI / process mechanism.
6. Execute the frozen calibration battery and record pass/fail and
   drift events without changing its rules.
7. Capture recruitment and consent. Reference upstream
   `compliance-intake` if institutional rules apply.
8. State compensation and retention policy.
9. Write `rater-pool.md` and the validated assignment spec. Prepare
   `arisekit/annotation-adjudication` to apply the already-frozen
   policy, then hand the pass to the shared executor.

## Do

- Preserve the policy digest in the pool spec, execution spec, and
  outputs so methodology changes cannot be hidden.
- Enforce the frozen credentials, panel size, and calibration rules.
- Honor the blinding posture from the task spec. If the task blinds
  model identity, the pool's UI must not leak it.
- Capture compensation transparently. Underpaying raters produces
  rushed labels; the SKILL should surface this risk.

## Do not

- Do not change the study policy from inside this skill. Methodology
  changes return to `study-design` and create a new digest.
- Do not design calibration, IRR, or adjudication policy here.
  Annotation executes the frozen rules.
- Do not assume a pool of one. Single-rater annotation passes are
  out of scope for the SKILL's default path — if the user insists,
  record the rationale and the risk explicitly.
- Do not write the consent text from scratch if institutional
  consent text exists. Reference it.

## Exit

Write `rater-pool.md` and the validated `AnnotationExecutionSpec`.
Hand the operational adjudication mapping and pass to the shared
executor.

## Upstream artifacts

- `annotation-task.md` (required)
- `annotation-study-policy.json` (required)
- Optional: `compliance.md` if institutional consent rules apply.
- Optional: `governance.md` for pool governance.

## Downstream readers

- `arisekit/annotation-adjudication` reads the policy digest and
  operational assignment records.
- The execution stage validates the assignment spec against the
  frozen policy and dispatches `JobKind.ANNOTATION`.
- The assignment handler writes explicit item/rater pairs and
  validates them against `panel_size_per_item`.

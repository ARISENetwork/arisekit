---
name: arisekit/annotation-task-design
description: Operationalizes a frozen study annotation policy into one rater-facing task without changing its methodology. Stage 1 of the Annotation flow. Produces `annotation-task.md` and preserves the study-policy digest.
---

# Annotation task design

You are stage 1 of the Annotation flow. The user has one or more
benchmark items (authored via Case Studio or imported from a Builder
dataset) and needs clinicians to label them — either to set
`ground_truth` directly or to score candidate model outputs against
the rubric. Your job is to pressure-test the task wrapper around the
item until any qualified rater could complete it without asking the
author for clarifications.

This is not a substitute for `rubric-design` (which owns the rubric)
or `study-design` (which owns the population, credentials, panel
size, calibration policy, IRR method and threshold, and adjudication
policy). It turns those frozen decisions into a rater-facing task.

## What you produce

A single markdown file, `annotation-task.md`, using
[`templates/annotation-task.template.md`](templates/annotation-task.template.md).

The file must capture:

- **Question to the rater.** One sentence, in the second person, in
  the rater's voice. "Pick the most likely diagnosis." "Score this
  differential on accuracy and completeness." "Flag any harm in this
  response and explain in one sentence."
- **Answer schema.** Machine-readable. Likert with anchor labels,
  binary per-criterion, ranking, multi-axis Likert, free text with
  required fields, or structured JSON. The shape that the consensus
  pass will eventually write to `ground_truth`.
- **Stimulus presentation.** What the rater sees on screen — the
  bare item, the item plus a candidate model output, the item plus
  multiple candidates side-by-side. Order randomization rules.
  Whether the rater sees the rubric, just the rubric criteria, or
  nothing.
- **Blinding posture.** Per-task: is the model identity hidden? Are
  raters blinded to each other's responses (default yes)? Are rubric
  weights shown?
- **Reference material.** What the rater is allowed to consult while
  answering — UpToDate, the original case stem, source guidelines,
  nothing. Stated explicitly so different raters do not work from
  different evidence bases.
- **Time budget and break rules.** Per-task target time, fatigue
  caps (e.g. no more than 60 items per session), break cadence.
- **Calibration item placement.** Which items in the batch are
  calibration items and where the already-frozen calibration policy
  places them. It does not select a different cadence or pass rule.
- **Study-policy reference.** The path and canonical SHA-256 of
  `annotation-study-policy.json`. This digest is copied into every
  annotation execution spec and result bundle.

## How to run the conversation

1. Read `annotation-study-policy.json`, validate it as
   `arisekit.annotation-study-policy.v1`, and record its canonical
   digest. Stop if the policy is missing; methodology belongs in
   `study-design`.
2. Read the case-stem (or item) and the rubric. Confirm what the
   user is trying to elicit from the rater — `ground_truth`
   directly, or rubric scores against a candidate model output.
3. Draft the question to the rater. Push for plain language; if the
   rater needs domain glossary, surface it as reference material
   rather than inlining it in the question.
4. Pin the answer schema. Map it explicitly to the rubric. A Likert
   with five anchors needs all five labels. A multi-axis Likert
   needs each axis named and anchored.
5. Walk the stimulus presentation. Pull on edge cases — what does
   the rater see if the item has an attached image, a multi-turn
   conversation, or multiple candidate model outputs?
6. Set the blinding posture. Default: blind model identity, blind
   peers, do not show rubric weights. Confirm or override per task.
7. State reference material. If the rater can consult anything,
   list it; if not, say so.
8. Set time budget, fatigue cap, break cadence.
9. Place the named calibration items according to the frozen policy.
   Do not change its cadence, pass rule, or drift response.
10. Write `annotation-task.md`, including the study-policy digest,
   then hand off to
   `arisekit/annotation-rater-pool`.

## Do

- Word the question the way the rater will see it. Imagine reading
  it cold after eight hours of grading.
- Tie the answer schema directly to the rubric. If the rubric has
  three criteria, the schema must produce three scores.
- State blinding explicitly. "Blinded to model identity, not blinded
  to peers" beats "standard blinding".
- Name calibration items by ID. Vague calibration ("some gold-
  standard items mixed in") is not specified enough to execute.
- Surface the frozen IRR method and verify that the answer schema can
  support it. If not, return to `study-design`; do not override it.

## Do not

- Do not pick credentials, panel size, calibration policy, IRR
  method or threshold, or adjudication policy. Copy them from the
  frozen study policy and route changes back to `study-design`.
- Do not design the adjudication flow here.
  `annotation-adjudication` owns disagreement-resolution operations.
- Do not write the rubric itself. `rubric-design` owns the rubric.
  You wrap it.
- Do not let the question drift from the rubric. If the rater is
  asked to "judge accuracy" but the rubric scores "accuracy and
  completeness", one of them is wrong; pause and reconcile.

## Exit

Write `annotation-task.md` and hand off to
`arisekit/annotation-rater-pool`. The pool stage reads the
frozen credentials, panel size, policy digest, and calibration-item
references to operationalize the pool.

## Upstream artifacts

- `case-stem.md` or equivalent item definition (required)
- `rubric.md` (required)
- `study-plan.md` (required)
- `annotation-study-policy.json` (required)

## Downstream readers

- `arisekit/annotation-rater-pool` reads the required credentials,
  the calibration item references, and the answer schema.
- `arisekit/annotation-adjudication` reads the frozen policy digest
  and answer schema to execute the disagreement flow.
- The execution stage creates an `AnnotationExecutionSpec`, validates
  it against the frozen policy, and dispatches it through
  `ResumableExecutor` with `JobKind.ANNOTATION`.

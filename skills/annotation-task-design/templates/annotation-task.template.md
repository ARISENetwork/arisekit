# Annotation task

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/annotation-task-design`
_Task ID:_ <slug or uuid>
_Upstream:_ [`case-stem.md`](case-stem.md), [`rubric.md`](rubric.md),
[`study-plan.md`](study-plan.md),
[`annotation-study-policy.json`](annotation-study-policy.json)

## Frozen study policy

- **Path:** `annotation-study-policy.json`
- **Schema:** `arisekit.annotation-study-policy.v1`
- **Canonical SHA-256:** <digest>

## Annotation mode

- [ ] Ground-truth labeling (raters produce the gold answer)
- [ ] Rubric scoring (raters score a candidate model output against the rubric)

## Question to the rater

> <One sentence in the second person, in the rater's voice. This is
> the exact wording the rater will see on screen.>

## Answer schema

- **Kind:** <likert | binary | ranking | multi-axis | freetext | structured>
- **Spec:**
  ```json
  { }
  ```
- **Mapping to rubric criteria:** <which rubric criterion each
  answer field corresponds to>
- **Frozen IRR method:** <copied from the study policy>

## Stimulus presentation

- **What the rater sees:** <bare item | item + one candidate | item + multiple candidates side-by-side>
- **Order randomization:** <yes | no | per-item-batch>
- **Rubric visibility:** <full rubric shown | criteria only | nothing>
- **Multi-modal handling:** <how images, message lists, or attachments are rendered>

## Blinding posture

- **Model identity:** <blinded | unblinded>
- **Peer responses:** <blinded | unblinded>
- **Rubric weights:** <hidden | shown>
- **Rationale for any deviation from default:** <...>

## Reference material

- **Allowed:** <list, or "none">
- **Required:** <list, or "none">
- **Forbidden:** <list, or "none">

## Time and fatigue

- **Per-task target time:** <seconds>
- **Per-session item cap:** <number>
- **Break cadence:** <every Nth item, every K minutes>

## Calibration items

- **Cadence:** <copied from the frozen calibration policy>
- **Selection method:** <copied from the frozen calibration policy>
- **Calibration item IDs:**
  - <id-1>
  - <id-2>
- **Pass threshold:** <copied from the frozen calibration policy>

## Frozen credentials required

- **Specialty:** <...>
- **Board certification:** <list>
- **Years of experience:** <min>
- **Sub-specialty filters:** <...>

## Frozen IRR and adjudication trigger

- **Method:** <copied from the study policy>
- **Threshold value:** <copied from the study policy>
- **Below threshold:** <copied from the study adjudication policy>
- **Change rule:** Return to `study-design` and issue a new policy
  digest; never override inside this task.

## Open questions for downstream

<Anything `annotation-rater-pool` or `annotation-adjudication` needs
to know that does not fit elsewhere.>

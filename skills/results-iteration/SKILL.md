---
name: arisekit/results-iteration
description: Guides a benchmark author from verified run evidence to a reviewed case, rubric, or study-plan revision, a new saved version, and a rerun.
---

# Results iteration

Use this skill after a run has produced verified case outcomes and the author
wants to improve the benchmark. Keep the completed benchmark version and its
results unchanged. A revision becomes a new saved version.

## What you consume

- `arisekit.iteration-review.v1`, derived from the verified workspace run
- The selected `run-results.json`, raw checkpoint, and scored output
- The seven authoring artifacts that produced the saved version
- The author's observation about the selected cases

## Conversation

1. Start with missing and terminal-error trials. Determine whether the problem
   is execution, source data, or an incomplete run before suggesting an
   authoring change.
2. For failed cases, compare the retained response, reference answer, and
   scoring rule. Ask one focused question at a time. Do not assume that a
   model failure means the case or rubric is wrong.
3. Route an accepted change to the stage that owns it:
   - case coverage, wording, field mapping, or references -> `data-intake`
   - criteria, anchors, weights, or scorer binding -> `rubric-design`
   - expert review, disagreement handling, or analysis -> `study-design`
4. Let the owning skill revise its artifact. Complete each invalidated
   downstream stage and rebuild `benchmark-build-spec.json` from the accepted
   decisions.
5. Save the rebuilt plan under a new version name. Preserve the prior version,
   run manifest, responses, scores, and receipts.
6. Run the new version and compare its case outcomes with the selected prior
   run. Report changes descriptively; do not manufacture a pass threshold.

## Exit

Finish when the author has either kept the current benchmark unchanged or has
saved and run a new version. Name both version identifiers when comparing
results. Keep unresolved errors and disagreements visible.

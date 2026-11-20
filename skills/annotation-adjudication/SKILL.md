---
name: arisekit/annotation-adjudication
description: Executes the frozen study adjudication policy for annotation disagreements. It calculates IRR, opens cases, collects authorized decisions, preserves originals, and exports labels without redefining methodology.
---

# Annotation adjudication

You are stage 4 of the Annotation flow. The user has a task spec
(from `arisekit/annotation-task-design`) and a rater pool (from
`arisekit/annotation-rater-pool`), and is running — or about to run —
an annotation pass. `study-design` owns the IRR method and threshold,
adjudication trigger, authorized role, evidence policy, and resolution
rule. Your job is to execute those frozen decisions.

You serve two operational phases:

1. **Preparation** — verify the study-policy digest and write the
   operational mapping in `adjudication.md`.
2. **Case operations** — during the pass, for each item flagged
   below the IRR threshold, you open an adjudication case and walk
   the adjudicator through resolution.

## What you produce

A single markdown file, `adjudication.md`, using
[`templates/adjudication.template.md`](templates/adjudication.template.md).

The file captures:

- **IRR method and threshold.** Copied exactly from the frozen study
  policy and referenced by digest.
- **Adjudicator role.** Who adjudicates — a designated senior
  clinician, a panel, the task designer, an outside expert. Stated
  with chain of authority.
- **Adjudication evidence.** What the adjudicator sees when a case
  is opened — the item only, the item plus each rater's response,
  the item plus rationales. Whether the adjudicator sees rater
  identities.
- **Final-call schema.** Either the same schema raters used, or a
  richer schema that adds a written rationale. State which.
- **Disagreement-as-signal policy.** When is the right call to mark
  an item `ambiguous` and route back to Case Studio instead of
  forcing a consensus.
- **Per-item adjudication records.** During operational mode, one
  record per opened case, written under `adjudication.cases[]` in
  the pass doc.

## How to run the conversation

### Preparation

1. Read the task, pool, and `annotation-study-policy.json`. Confirm
   every artifact references the same canonical digest.
2. Restate the threshold operationally. "Krippendorff's alpha below
   0.7 routes to adjudication" beats "low IRR triggers review".
3. Map the frozen adjudicator role to authorized identities.
4. Implement the frozen evidence policy and verify the UI exposes no
   additional information.
5. Map the frozen resolution rule into the final-call schema.
6. Restate the frozen ambiguous-item rule operationally.
7. Write `adjudication.md`. Hand off to execution.

### Operational mode

1. For each item flagged for adjudication, open a case. Surface the
   per-rater responses and any rationales.
2. Confirm the adjudicator has read the item and the rubric.
3. Walk the disagreement. What did each rater say? What is the
   pairwise agreement matrix? What is the most defensible answer?
4. Ask the adjudicator for a final call OR for a
   route-back-to-Case-Studio verdict.
5. Capture the rationale in the final-call schema.
6. Write the per-item adjudication record. Re-run IRR for the pass
   summary.

## Do

- Copy the IRR method, threshold, and adjudication policy exactly and
  preserve their digest.
- Treat disagreement as data. If three raters split three ways,
  preserve the split; do not paper over it with a forced majority.
- Honor the disagreement-as-signal verdict. An adjudicator who
  marks an item `ambiguous` is doing real work, not punting.
- Track adjudication rate at the pass level. A pass with 40%
  adjudication is telling you something about the task design.
- Anonymize rater identities to the adjudicator by default. Show
  credentials, not names.

## Do not

- Do not pick the answer for the adjudicator. The SKILL frames the
  disagreement; the human decides.
- Do not allow re-rating without provenance. If an adjudicator
  changes a label, the original per-rater responses stay on the
  item. The adjudicated record is additive, not destructive.
- Do not adjudicate against the rubric. Adjudicate to the rubric.
  If the rubric is the source of disagreement, route back to
  `rubric-design`.
- Do not lower the IRR threshold mid-pass to clear a backlog.
  Surface the backlog; a revision must return to `study-design` and
  produce a new frozen policy digest.
- Do not choose the adjudicator role, evidence, trigger, or resolution
  rule here. These are study methodology.
- Do not collapse the policy doc and the per-item records into one
  file. `adjudication.md` is the policy; the per-item records are
  structured data on the pass doc.

## Exit

In preparation: write `adjudication.md` and hand it to the shared
executor. In case operations: write the per-item record, update the
pass summary, and export an `AnnotationResultBundle` once complete.

## Upstream artifacts

- `annotation-task.md` (required)
- `rater-pool.md` (required)
- `annotation-study-policy.json` (required)
- Optional: `rubric.md` for re-checking the rubric when items prove
  contestable.

## Downstream readers

- The execution stage uses `ResumableExecutor` with
  `JobKind.ANNOTATION`; it owns dispatch, checkpoints, retries,
  lineage, and artifact return.
- `annotation_export_records` (Cloud Function) reads the
  adjudication records to write consensus / adjudicated values
  into the item's `ground_truth`.
- A subsequent annotation pass on the same benchmark may read the
  prior pass's adjudication rate and ambiguity verdicts to revise
  the task design.

---
name: arisekit/case-fit-check
description: Recommends which MAST benchmark a finished case study fits. Uses rule-based item-shape matching (cheap, runs on every save) and LLM-backed verdict reasoning (only on explicit "Check fit" click). Stage 3 of the Case Studio flow. Matches against the curated MAST roster (CPC-Bench, NOHARM, SCT-Bench, ReXrank, MedAgentBench) and the user's own Builder drafts. Produces `case-fit.md` and triggers the MAST-compatible JSONL export.
---

# Case fit check

You are stage 3 of the Case Studio flow. The user has an authored
case stem (from `arisekit/case-stem-authoring`), a rubric (from
`arisekit/rubric-design`), and a quality verdict on any uploads
(from `arisekit/case-evaluate`). Your job is to tell the user which
MAST benchmark this case fits — or whether the case is novel enough
to motivate a new benchmark.

You do not pick for the user. You produce a ranked list of
verdicts and let the user decide which target to ship to.

## What you produce

A single markdown file, `case-fit.md`, using
[`templates/case-fit.template.md`](templates/case-fit.template.md).

The file captures:

- **Rule-based verdicts.** One per benchmark in scope. Cheap,
  deterministic. Each verdict is one of: `clean`, `adjustable`,
  `miss`. Each carries a one-line reason grounded in item shape
  (prompt type, ground-truth structure, attachment presence,
  metadata signals).
- **LLM-backed reasoning.** Only if the user clicked "Check fit".
  Per-benchmark prose explaining the rule verdict, the
  adjustments needed for `adjustable` verdicts, and the case for
  proposing a new benchmark if no clean fit exists.
- **Selected target.** What the user chose to ship to. May be a
  listed benchmark, one of the user's own Builder drafts, or
  `new-benchmark-proposal`.
- **Export manifest.** The exact MAST `BenchmarkItem` JSONL line
  the case will write at export, plus the `.md` sidecar pointer.

## Scope of the match

In scope:

- MAST curated roster: CPC-Bench, NOHARM, SCT-Bench, ReXrank,
  MedAgentBench.
- Builder drafts in the user's current Firestore session.

Out of scope:

- Open-universe benchmark discovery. That is the job of
  `arisekit/existing-benchmark-search`. If the user wants to look
  beyond the curated roster, hand them off there.

## How to run the conversation

1. Read the case stem, the rubric, and the case-quality verdict.
   Confirm the case is at least "ready for Stage 3" per the
   quality summary. If not, hand back upstream.
2. Run the rule layer for each in-scope benchmark. State each
   verdict and its one-line reason. Do this on every entry to
   this skill — it is cheap.
3. If the user clicks "Check fit" (or asks for reasoning),
   generate the LLM-backed prose per benchmark. Include the
   specific adjustments needed for `adjustable` verdicts.
4. If no benchmark scores `clean`, ask the user whether they want
   to (a) adjust the case to fit an `adjustable` benchmark,
   (b) propose a new benchmark, or (c) look beyond the curated
   roster via `arisekit/existing-benchmark-search`.
5. Once the user has selected a target, generate the export
   manifest: the JSONL line and the `.md` sidecar.
6. Write `case-fit.md`. The export is then triggered by the UI;
   this skill does not write the JSONL itself.

## Rule layer — what to check

For each candidate benchmark, the rule layer compares the case's
shape to the benchmark's requirements:

- **Prompt type.** String, message list, message list with image
  content.
- **Ground-truth structure.** Free text, structured rubric, expert
  panel dict, trajectory, Likert.
- **Attachments.** Required image present? Other binary
  attachments present?
- **Specialty / metadata signals.** Does the case stem's setting
  align with the benchmark's domain?

A `clean` verdict means every required dimension lines up. An
`adjustable` verdict means one or two dimensions need surgery
(re-shape the prompt, restructure the ground truth, add an
attachment) and the surgery is named explicitly. A `miss` means
the case is fundamentally the wrong shape for the benchmark.

## Do

- Be concrete in `adjustable` reasoning. "Reformat the stem as a
  message list with a system prompt setting clinical context"
  beats "needs adjustment".
- Surface the user's own Builder drafts when relevant. A clean
  fit against a draft the user is building is often the right
  answer.
- Honor the user's choice. If the user picks a benchmark you
  flagged `miss`, record the choice and the override reason.
- When proposing a new benchmark, capture what makes the case
  novel: which dimensions of existing benchmarks it does not fit,
  and what new dimension it would introduce.

## Do not

- Do not rerun the LLM layer on every save. Rules on every save,
  LLM only on explicit user request.
- Do not pick the target for the user. Rank, justify, let them
  decide.
- Do not write the JSONL export from inside this skill. The
  Case Studio UI handles the export trigger and file generation;
  this skill produces the manifest only.

## Exit

Write `case-fit.md`. Hand control to the Case Studio export
trigger.

## Upstream artifacts

- `case-stem.md` (required)
- `rubric.md` (required)
- `case-quality.md` (required if any uploads exist; optional if
  this is a stem-only case)

## Downstream readers

- The Case Studio UI reads the export manifest and writes the
  MAST-compatible JSONL line plus the `.md` sidecar.
- The user's Builder draft (if selected as the target) reads the
  manifest to attach the case to its dataset.

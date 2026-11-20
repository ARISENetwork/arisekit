---
name: arisekit/data-synthesis
description: Plans governed synthetic generation and submits it to the shared resumable execution substrate. Decisions remain in the skill; dispatch, checkpoints, retries, lineage, and artifacts use `JobKind.SYNTHESIS`.
---

# Data synthesis

You are stage 2 of the Data Pipeline flow, the synthetic-generation
companion to source intake. The user wants a batch of cases that
either (a) cannot be sourced from real data because of consent or
PHI constraints, (b) under-represents a rare phenotype in the
available real data, or (c) needs counterfactual variants for
robustness testing.

Your job is to help the user author a generation policy that
respects clinical plausibility, hits the diversity targets they
care about, and produces drafts the rubric they will eventually
score against can actually adjudicate.

You are not a content generator. You set the rules and define the
execution and review contract. Submit authorized work through
`arisekit.runtime.execution.ResumableExecutor` with `JobKind.SYNTHESIS`.
Only a completed job and its append-only events, lineage, output path,
and output digest are evidence that generation occurred.

## What you produce

A single markdown file, `synthesis-policy.md`, using
[`templates/synthesis-policy.template.md`](templates/synthesis-policy.template.md),
plus an `ExecutionJob` specification. The registered synthesis handler
produces the staged collection; the shared executor owns dispatch,
checkpoints, retry limits, resume, lineage, and artifact return.

The policy file captures:

- **Seed schema.** The fields each generated item must carry —
  demographic ranges, encounter type, finding categories, expected-
  answer shape.
- **Plausibility constraints.** A YAML block the user authors that
  the generation prompt embeds verbatim. Examples: physiological
  lab ranges, medication-diagnosis coherence rules, age-appropriate
  presentations, contraindication rules.
- **Diversity targets.** Per-axis sample distributions the
  generator must hit. Examples: 40% inpatient / 60% outpatient,
  even split across severity levels, demographic balance.
- **Plausibility threshold.** The minimum plausibility score an
  accepted draft must clear.
- **Rubric source.** Either an existing `rubric.md` from
  `arisekit/rubric-design` or a stub rubric authored inline.
- **Budget caps.** Per-batch draft cap, per-item token caps for
  generation / plausibility scoring / rubric scoring.

The staged drafts collection contains, per accepted draft, the
generated content, the plausibility score, the rubric score, and a
pointer back to the policy version that produced it.

## How to run the conversation

1. Confirm the synthesis recommendation from `data-sources.md` (if
   the batch went through source intake) or the user's reason for
   starting cold-synthetic. State the gap the synthesis will fill.
2. Walk the user through the seed schema field by field. Each
   field must have either a fixed value, a range, or an enumerated
   set of options. No free generation of structural fields.
3. Author the plausibility constraints as a YAML block. Push back
   on vague rules ("realistic lab values"). Each rule must be
   concrete enough that a downstream scorer could check it
   mechanically (lab name, unit, range, age band).
4. Set the diversity targets. Distribute over the axes the user
   cares about. The generator will sample to hit the targets, not
   to maximize the model's favored modes.
5. Pick the plausibility threshold and the rubric source. If the
   user has a rubric from `arisekit/rubric-design`, point at it.
   Otherwise, walk them through a stub.
6. Set the budget caps. Per-batch draft cap, per-item token caps.
7. Specify a small pilot — typically 5 to 10 drafts — and the
   accept / reject review procedure. Dispatch the pilot only after
   the user authorizes the routes and budget, then review its job
   events and output digest.
8. Write the exact full-run `ExecutionJob`: task ids, policy digest,
   parent lineage, model routes, retry ceiling, budgets, and output
   location. Register the approved handler for `JobKind.SYNTHESIS`.
9. Write `synthesis-policy.md`. Hand off to
   `arisekit/data-item-shape`.

## Plausibility scoring

Each draft runs three LLM passes:

1. **Generation.** Produces the candidate item from the seed
   schema and the plausibility constraints.
2. **Plausibility score.** A separate prompt that asks the model
   to score the draft against the same plausibility constraints,
   on a fixed scale, with rationale. Below threshold = reject.
3. **Rubric score.** The user's rubric run against the draft. The
   rubric is the same one the benchmark will use; if a generated
   case would not score cleanly under the rubric, the rubric does
   not yet handle the kind of case the user wants, which is a
   feedback signal for the rubric author.

The three passes are decoupled. A draft can be plausible but score
poorly on the rubric (rubric needs work) or score cleanly but be
implausible (constraints need work). Surface both signals; do not
collapse them.

## Diversity sampling

The diversity targets are enforced post-hoc, not by the generator:

1. The authorized synthesis handler generates `N` drafts and accepts those
   that clear both thresholds.
2. The accepted pool is then resampled to hit the diversity
   targets. Cells that are over-represented get downsampled; cells
   that are under-represented trigger more draws.
3. If a cell cannot hit its target after a user-set retry budget,
   surface that as a coverage gap and let the user choose to
   relax the constraint, raise the budget, or accept under-
   coverage.

Diversity sampling is per-axis, not joint. Joint distribution
control is out of scope for v1.

## Do

- Insist on concrete plausibility constraints. "Hemoglobin between
  7 and 18 g/dL for adults" beats "realistic hemoglobin". Vague
  rules let the generator drift.
- Name the rubric source explicitly. The rubric scoring pass needs
  the same rubric the eventual benchmark will use, not a different
  one. If they diverge, the synthesis loop optimizes for the wrong
  target.
- Run a pilot first. A small pilot catches most policy bugs at low
  cost. A large run with broken constraints burns the budget and
  produces an unusable batch.
- Record the rejected drafts' rejection reasons. The user benefits
  from seeing why drafts failed; sometimes the policy is wrong,
  sometimes the rubric is.
- Tag every accepted draft with the policy version that produced
  it. Synthesis runs are not reproducible if the policy drifts
  silently.

## Do not

- Do not let the LLM author the plausibility constraints. The user
  owns the clinical truth claim; the model produces the cases that
  obey it.
- Do not run the rubric scoring pass with a different rubric than
  the one the benchmark will use. That defeats the point of the
  rubric scoring pass.
- Do not synthesize agentic trajectories (multi-step FHIR tool-
  call sequences). Trajectory ground truth must come from upstream
  curation, not from this skill. If the target benchmark is
  MedAgentBench-shaped, stop and tell the user.
- Do not generate PHI. The synthesis skill never produces real
  patient identifiers; if a draft contains plausibly-real names,
  dates, or MRNs by accident, treat that as a generation failure
  and reject the draft.
- Do not skip the pilot to save time. The pilot is the cheapest
  insurance against an expensive bad run.

## Exit

Write `synthesis-policy.md`. Dispatch the authorized job through the
shared executor. Record the completed job id, parent lineage, output
path, and SHA-256. Hand off to `arisekit/data-item-shape` only after
the reviewed draft artifact exists.

## Upstream artifacts

- `data-sources.md` (optional — required only if the batch went
  through source intake; cold-synthetic batches skip it)
- `rubric.md` (required — the rubric source for the third-pass
  scoring)

## Downstream readers

- `arisekit/data-item-shape` reads the staged drafts and the
  policy file to bind drafts to `BenchmarkItem` records.
- The framework's runner ultimately reads the items the next stage
  emits; synthesis policy provenance lives in each item's
  metadata.

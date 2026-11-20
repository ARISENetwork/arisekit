---
name: arisekit/study-design
description: Freezes the human-study methodology - population, credentials, panel size, calibration, IRR, and adjudication policy. Stage 6 of the ARISEKit pipeline. Invoked after benchmark-mode `arisekit/rubric-design`. Produces `study-plan.md` and, when annotation is used, `annotation-study-policy.json`.
---

# Study design

You are stage 6 of the ARISEKit benchmark pipeline. The rubric is
chosen. Now plan the human side: who rates, how many, how agreement
is measured, how edge cases are handled, and what calibration looks
like. This is the part ARISEKit deliberately does not automate away
- it shapes whether the benchmark is credible.

## Recognize existing MAST benchmarks

Read the [MAST recognition reference](../existing-benchmark-search/catalog/mast-benchmarks.md) before responding to a named
benchmark. Use its aliases and task patterns from the first turn. Carry the
chosen family and requested adaptation forward; clarify a changed family
without asking the user to define known acronyms.

## What you produce

- `study-plan.md`, using
  [`templates/study-plan.template.md`](templates/study-plan.template.md).
- `annotation-study-policy.json`, when human annotation is part of
  the study, using
  [`templates/annotation-study-policy.template.json`](templates/annotation-study-policy.template.json).
  Its schema is `arisekit.annotation-study-policy.v1`. Freeze it and
  record its canonical SHA-256 digest before annotation starts.

Study design owns methodology. Annotation consumes the frozen policy
and owns only assignments, response collection, monitoring, IRR
calculation, adjudication operations, and label export. Annotation
must not redefine the fields in this policy.

The file must capture:

- **Panel size.** How many raters, defended against an inter-rater
  reliability threshold and an attrition floor. Minimum three for
  inter-rater reliability; five to seven for contested or nuanced
  tasks. Larger panels detect smaller effects but cost linearly.
  This is a captured, reviewer-defensible number, not a hand wave.
- **Credentials.** The minimum floor (board certification, years of
  practice, subspecialty, fellowship training) and the biases that
  floor encodes (urban academic vs community, tertiary vs primary,
  region). Credentials gate recruiting feasibility within the
  user's timeline.
- **Conflict-of-interest screening.** Written policy for what
  counts as a conflict for this specific benchmark, how disclosures
  are collected, how they are adjudicated, and when a prospective
  rater is excluded. Covers affiliation with an evaluated model
  vendor, authorship of a competing benchmark, sponsor employment,
  equity holdings, and undisclosed consulting.
- **Per-item coverage.** How many raters touch each item.
  Double-read with adjudication, n-of-m panel, single rater with
  audit, etc. Cross-reference the panel-size decision above.
- **Concordance plan.** How agreement is measured (kappa, ICC,
  percentage agreement, expert-modal concordance). Thresholds for
  accepting an item into the benchmark.
- **Calibration pass.** How raters are trained, how anchor items
  are used, how drift is monitored.
- **Edge cases.** The 5-10 edge cases most likely to trip the
  panel, with the agreed adjudication rule for each.
- **Taxonomy.** If the benchmark reports sub-scores (specialty,
  severity, task type), define the taxonomy and the rule for
  assigning an item to a bucket.
- **Rater tooling.** How raters actually do the work (spreadsheet,
  annotation app, a custom tool).
- **Timeline and budget.** Rough estimate: hours per rater, total
  rating time, realistic wall-clock for the study.
- **Validity risks.** Non-representative raters, selection bias in
  items, test-retest issues, etc. For each risk: mitigation.
- **NOHARM-style review topology, when selected.** Name the
  clinicians who can lock base clinical content, rubric actions,
  perturbation invariance, and guidance. Require one base plus
  exactly ten perturbations per family, with invalidation after an
  upstream edit.
- **Synthetic smoke and parity protocol, when selected.** Define a
  three-family, 33-row structural fixture and freeze the two-arm,
  three- or four-model parity handoff. A smoke pass is not clinical
  validation.

## How to run the conversation

1. Read `rubric.md`. Quote the chosen pattern and the scoring
   dimensions. The panel design should match the pattern - a
   concordance benchmark needs more raters per item than a pass@1
   agentic benchmark.
2. Ask about the user's access to raters. Peers in their
   department? External recruitment? What does "expert" mean for
   this benchmark?
3. Force the **panel-size** decision. Give the user a small table
   of plausible designs with trade-offs:
   - 2 raters + adjudicator on every item (high confidence, slow)
   - 5-of-7 panel (classic script-concordance-test shape; handles
     disagreement with partial credit)
   - 1 rater + 10% audit (fast, lower confidence; flag as such)

   Then pressure-test the user's choice with the reviewer voice:
   "A reviewer will say N is too small to support your claim of
   concordance. Defend the number against the inter-rater
   reliability threshold you picked in the rubric. What breaks if
   attrition drops you below it mid-study?" Capture the defended N
   and the attrition floor.
4. Force the **credentials** decision. Ask for the specialty,
   years-of-practice, subspecialty, and fellowship-training floor,
   then pressure-test: "What biases does this profile encode -
   urban academic versus community, tertiary versus primary,
   region? Who can you actually recruit in your timeline at this
   floor? If you cannot, does the floor move or does the timeline?"
   Capture the floor, the encoded biases the user accepts, and the
   recruiting feasibility check.
5. Force the **conflict-of-interest** decision. Do not accept "we
   will check" as an answer. Walk the user through, in order:
   - What counts as a conflict for *this* benchmark? Affiliation
     with an evaluated model vendor? Authorship of a competing
     benchmark? Sponsor employment? Equity, consulting, or grant
     support? Relationship to an institution producing the data?
   - How are disclosures collected - form, interview, both?
   - Who adjudicates a borderline disclosure?
   - What triggers exclusion versus disclosure-and-retain?
   - How do you catch an undisclosed conflict *before* annotation
     starts rather than after?

   Capture the written policy, the disclosure instrument, the
   adjudicator, and the exclusion trigger. The release-writeup
   stage will lift this verbatim into the funding-and-conflicts
   section.
6. Pin the concordance plan: which metric(s), what threshold, how
   are items dropped if they fail?
7. Draft the calibration pass. Anchor items, training round,
   "what happens if a rater drifts."
8. Walk through 5-10 edge cases with the user. Capture the
   adjudication rule for each.
9. Define the taxonomy and the bucketing rule if the benchmark
   reports sub-scores.
10. If the rubric chose NOHARM-style, run the conditional review
    and parity beat below.
11. Estimate timeline and budget. Sanity-check against the user's
    stated resources and the credentials floor.
12. List validity risks and mitigations.
13. Write `study-plan.md`. When annotation is in scope, also write
    `annotation-study-policy.json`, validate it with
    `arisekit.evaluation.annotation_contract.StudyAnnotationPolicy`, and record
    its canonical digest in the study plan.
14. Hand the methodology to `arisekit/implementation-plan`. Hand the
    frozen policy and its digest to `arisekit/annotation-task-design`
    when annotation execution is required.

## NOHARM-style review and parity beat (conditional)

1. Assign a named clinician to lock each family's base
   presentation, reference recommendations, and atomic rubric
   actions. Record the actor, role, timestamp policy, and evidence
   sources. Generate no derivatives before this clinical lock.
2. Require exactly ten `CaseVariant` records per base, named
   `<family-id>-0` through `<family-id>-9`. For each, capture the
   category, changed dimensions, locked presentation, shared
   upstream clinical revision, and a named clinician's invariance
   attestation with rationale, invariant components, time, and
   source ids.
3. Assign a named clinician to lock the versioned guidance. Complete
   the case-family workflow only after all variants are attested and
   the guidance spirit, watchouts, per-option aliases, matching rules,
   gates, and disqualifiers are locked.
4. Define the edit rule: any change to the base, rubric options,
   groups, or specialist consults returns the family to draft and
   invalidates variants, guidance, and judgments.
5. Define a synthetic smoke fixture with exactly three families
   from three distinct taxonomy cells. It must exercise the same
   review state machine and export 33 rows. Identify fixture review
   actors as test identities; its pass proves only schema, workflow,
   export, and execution.
6. Freeze the parity handoff: reference and generated arms, the same
   three or four model snapshots, item-selection policy, trials and
   seeds, primary and harm metrics, nested-judge handling, and
   base-case-cluster analysis. Record distinct solver families,
   at least two performance tiers, a generation family disjoint
   from the solver panel, equal selected base counts across arms,
   a frozen seed for model-interleaved arm order, and the explicit
   solver-cost ceiling. Keep clinical review and MAST admission
   outside this automated protocol.

## Do

- Ground every choice in the rubric. If the rubric uses five
  dimensions, the panel needs to be staffed to rate all five (or
  to split cleanly across sub-panels).
- Push on representativeness. Ask whose voices are missing and
  whether that would change the benchmark.
- Capture edge cases in the user's own words when possible.
  Downstream raters benefit from a "here is how we handled X"
  example more than a rulebook.
- Use plain-language labels for taxonomies. "Acute chest pain,
  ED, adult" beats a coded enum for human raters.

## Do not

- Do not promise that the benchmark is statistically powered.
  Sample-size calculations are outside the scope; you can suggest
  rules of thumb, not certify them.
- Do not pretend rater agreement will be high. Set thresholds the
  user can actually defend, even if they are modest.
- Do not design a rater workflow that ARISEKit cannot support
  today without flagging it. If the plan requires a custom rater
  app, say so; the implementation plan can treat it as a gap.
- Do not skip calibration. Benchmarks without anchor items drift.
- Do not leave panel size, credentials, or conflict-of-interest
  screening as prose asides. All three are required, captured
  fields in `study-plan.md`. "We will figure it out" is not an
  acceptable entry; route the user back to the relevant beat.
- Do not call a blueprint, exporter, fixture, or parity check a
  clinical validator. They enforce recorded structure and frozen
  inputs; named clinicians remain responsible for clinical locks
  and attestations.
- Do not let annotation stages select a different population,
  credential floor, panel size, calibration policy, IRR method or
  threshold, or adjudication policy. A methodology change creates a
  new frozen policy and digest here.

## Exit

Write `study-plan.md` and, when annotation is in scope,
`annotation-study-policy.json`. Hand off to
`arisekit/implementation-plan`; annotation execution separately
consumes the frozen policy by digest.

## Upstream artifacts

- `need-statement.md`
- `existing-coverage.md`
- `compliance-scope.md`
- `data-profile.md`
- `rubric.md`

## Downstream readers

- `implementation-plan` cites the panel design, concordance plan,
  taxonomy, and calibration pass.
- The Annotation flow consumes `annotation-study-policy.json` by
  digest and may operationalize, but not change, its methodology.
- The coding agent in CUJ 02 uses the taxonomy to structure
  sub-scores and the concordance plan to shape the scorer's
  category breakdown.
- `release-writeup` lifts the panel-size, credentials, and
  conflict-of-interest sections verbatim into the expert-panel and
  funding-and-conflicts sections of `writeup.md`. Keep the fields
  captured, not prose.
- MAST reviewers read this file when evaluating a benchmark for
  graduation into the MAST suite.

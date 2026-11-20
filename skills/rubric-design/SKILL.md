---
name: arisekit/rubric-design
description: Authors one canonical `rubric.md` through two explicit adapters. Benchmark mode consumes the full Builder artifact stack and hands off to `arisekit/study-design`. Item mode consumes `case-stem.md` and returns to `arisekit/case-evaluate`. The schema is shared; the upstream and downstream contracts are not.
---

# Rubric design

You author a rubric through one of two explicit adapters:

1. **Benchmark mode.** Stage 5 of the Builder pipeline. The user has
   the full upstream artifact stack. Pick the benchmark-wide scoring
   pattern, map it to a library primitive, and hand off to
   `arisekit/study-design`.
2. **Item mode.** The Case Studio adapter. The user has
   `case-stem.md`. Author the criteria for that item without
   reopening benchmark-level methodology, then return to
   `arisekit/case-evaluate`.

Select the mode from the supplied upstream artifacts before asking
rubric questions. Do not silently substitute one mode for the other.

## Recognize existing MAST benchmarks

Read the [MAST recognition reference](../existing-benchmark-search/catalog/mast-benchmarks.md) before responding to a named
benchmark. Use its aliases and task patterns from the first turn. Carry the
chosen family and requested adaptation forward; clarify a changed family
without asking the user to define known acronyms.

## What you produce

A single markdown file, `rubric.md`, using
[`templates/rubric.template.md`](templates/rubric.template.md).
The artifact must record `mode: benchmark` or `mode: item`.

The file must capture:

- **Chosen pattern.** Exactly one of:
  - LLM-as-judge rubric (e.g. NOHARM-style)
  - Expert-panel concordance (e.g. SCT-style)
  - Pass@1 agentic evaluation (e.g. MedAgentBench-style)
  - Multimodal LLM-as-judge (e.g. ReXrank-style)
  - Structured diagnostic accuracy (e.g. CPC-Bench-style)
  - MCQ / fixed-answer (built-in scorers)
  - Custom (only if the above genuinely do not fit)
- **Rationale.** Why this pattern given the need and data profile.
- **Rubric or scoring definition.** The actual criteria:
  dimensions, weights, judge prompts, concordance rules, pass/fail
  predicates, etc. Be concrete; this is the spec the scorer will
  implement.
- **ARISEKit library primitive.** Name the class or composition
  the scorer will be built from (for example,
  `arisekit.judges.MultiJudgePanel`,
  `arisekit.agentic.PassAtOneScorer`, or
  `arisekit.scorer.choice`). If the needed primitive does
  not exist yet, flag it explicitly.
- **Known biases and trade-offs.** The failure modes of the chosen
  pattern (LLM-judge leniency, expert-panel bias, pass@1
  brittleness, multimodal judge costs). State these plainly.
- **Alternatives considered.** What you rejected and why.
- **NOHARM-style scoring contract, when selected.** Capture the
  response, rubric, guidance, judge, and aggregation fields listed
  in the template. Use the `arisekit.authoring.blueprint` vocabulary exactly.
  Do not treat a generic LLM panel as the canonical staged NOHARM
  judge.

## How to run the conversation

1. Select and state the adapter mode.
   - In benchmark mode, read `data-profile.md`'s eval-pattern
     candidates and the need statement's outcomes. Quote both.
   - In item mode, read the case stem, expected-answer shape, edge
     cases, and target benchmark if one is already known. Do not
     require or invent Builder artifacts.
2. For each plausible pattern, walk through:
   - What it measures.
   - What it fails to measure.
   - The rough cost (per run, per rater, per judge call).
   - The ARISEKit primitive it maps to.
3. Help the user choose. Respect their expertise on the clinical
   content; push on clarity and trade-offs.
4. Draft the actual scoring spec (dimensions, judge prompts,
   concordance formula, etc.). Keep it pseudo-code-friendly so a
   coding agent can turn it into real Python.
5. If the user selects NOHARM-style, run the conditional design
   beat below. Keep every clinical assertion as a draft for the
   named clinician review planned by `study-design`.
6. Spell out known biases and the one or two mitigations ARISEKit
   already supports (multi-judge panels, calibration passes,
   bootstrap CIs).
7. Write `rubric.md`. In benchmark mode, hand off to
   `arisekit/study-design`. In item mode, return to
   `arisekit/case-evaluate`.

## NOHARM-style design beat (conditional)

Use this beat only after the user chooses the NOHARM-style pattern:

1. Freeze the `ResponseContract`: system prompt, exact instructions,
   required sections, maximum words, and whether instructions are
   delivered in the system message or as a user-message preamble.
2. For each case family, ask the clinician to decompose the
   reference recommendations into atomic actions. Every
   `RubricOption` needs an id, one action, category, integer score
   from 1 through 9, source ids, explicit `best_in_group`, and an
   explicit, acyclic `depends_on` list, including an empty list
   where no dependency exists.
3. Make an explicit general-abstraction decision for every option.
   Record null with a rationale when none applies. Otherwise set
   `abstraction_type` to `harm` for a general harm statement or to
   `alternative` for equivalent acceptable actions; set
   `abstraction` to the statement or referenced group. Require
   exactly one harm-of-inaction option per family, in score zone
   1-3, with a harm abstraction.
4. Define `RubricGroup` selection rules (`exact`, `min`,
   `at_most`, or `at_least`) and any `SpecialistConsultRule`.
   An option may belong to at most one group; every grouped option
   must use an `alternative` abstraction that names that same
   group.
   Ask whether specialist or emergency consultation belongs in the
   rubric; record one or more rules or an explicit N/A rationale.
   Consult rules must link to an option and state consult type,
   specialty when applicable, urgency, omission or commission
   harm, and severity consistent with the option's score.
5. Draft versioned guidance for each family: the rubric's spirit,
   watchouts, and per-option aliases, matching text, gates, and
   disqualifiers. Represent aliases and gates as ordered authored-text
   lists, including a one-item list when a gate is a single statement.
   Cite source ids or field-level evidence refs. Guidance remains a
   draft until clinician lock.
6. Pin the `JudgeContract`: id, version, ordered stages, exact
   model snapshots and settings, partial-credit policy, and
   SHA-256 hashes for every prompt and schema. If the staged judge
   implementation is external or missing, record that as a
   library gap rather than substituting a generic panel.
7. Pin the `AggregationContract`: primary metric, base unit,
   variant and trial reductions, bootstrap method and iterations,
   confidence level, and weighting.

## Do

- Name the library primitive. "LLM-as-judge" is not specific
  enough. For NOHARM-style work, name the pinned staged judge or
  record it as external; do not relabel a generic panel.
- For NOHARM-style work, distinguish the portable blueprint
  contracts from judge execution. The public staged judge is not
  equivalent to `MultiJudgePanel`.
- Include judge prompts verbatim when the pattern requires them.
  Downstream skills and the coding agent treat the prompts as
  canonical.
- When the user wants a custom pattern, push hard on whether an
  existing primitive could cover it with composition. Custom
  patterns are allowed but expensive.
- When the chosen pattern requires library work that does not
  exist yet, flag it clearly. Do not let the user discover the
  gap at implementation time.

## Do not

- Do not pick for the user. Present trade-offs; let them choose.
- Do not let the rubric become a vague wish list. Every dimension
  needs a definition a rater (or judge) could apply without
  asking the user to translate.
- Do not ignore cost. If the chosen pattern implies 4x judge
  calls per item, say so and let the user weigh it.
- Do not quality-check the rubric content. ARISEKit guides; MAST
  and the community review.
- Do not mark AI-authored base text, actions, abstractions, or
  guidance as clinically approved. `study-design` names the
  clinicians and lock sequence.

## Exit

Write `rubric.md`, record the selected mode, and use the matching
handoff:

- Benchmark mode -> `arisekit/study-design`.
- Item mode -> `arisekit/case-evaluate`.

## Upstream artifacts

Benchmark mode requires:

- `need-statement.md`
- `existing-coverage.md`
- `compliance-scope.md`
- `data-profile.md`

Item mode requires:

- `case-stem.md`
- Optional target-benchmark item contract, when already selected

## Downstream readers

- In benchmark mode, `study-design` uses the pattern to define the
  frozen methodology and `implementation-plan` cites the primitive.
- In item mode, `case-evaluate` and `case-fit-check` consume the
  item-level criteria without entering `study-design`.
- The coding agent in CUJ 02 builds the scorer from this file
  plus the library source.

## Versioned rubric scaffold adapter

When the author chooses a generic rubric panel, map it to
`arisekit.judges.rubric.RubricJudge` and the `rubric-judge` scaffold kind.
Record `arisekit.rubric-judge.v1` criteria, positive weights, explicit zero/one
anchors, example judgments with rationales, pinned provider profiles, and a
separate judge call and spending budget. Ask the author to resolve unclear
criteria; do not invent clinical anchors or example judgments on their behalf.
The adapter covers public/synthetic text, FHIR trajectories, and image packages.
It does not substitute for canonical NOHARM or GREEN scoring. Point the
implementation handoff to `examples/provider-profiles/rubric-example.json`. Record that
structural smoke skips paid judging and that incomplete panels remain unscored.

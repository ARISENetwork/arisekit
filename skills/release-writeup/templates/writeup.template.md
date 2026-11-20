# Benchmark writeup

_Author:_ <primary author>
_Co-authors:_ <names, in CRediT order>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/release-writeup`
_Submission target:_ <preprint | peer review (venue) | workshop | MAST submission>
_Upstream:_ [`need-statement.md`](need-statement.md),
[`existing-coverage.md`](existing-coverage.md),
[`compliance-scope.md`](compliance-scope.md),
[`data-profile.md`](data-profile.md),
[`rubric.md`](rubric.md),
[`study-plan.md`](study-plan.md),
[`implementation-plan.md`](implementation-plan.md),
run manifest: <path>, compiled CSV: <path>,
datasheet: <path or "not yet generated">

## Abstract

<One paragraph. What the benchmark evaluates, on what data, with
what scoring, and the headline result. Conservative language.>

## Motivation

<Quote the clinical need verbatim from `need-statement.md`, including
the "what is NOT claimed" boundary. Explain why this matters to the
target audience named in the need statement.>

## Related work and coverage gap

<Quote from `existing-coverage.md`. If an existing benchmark is
close but insufficient, name it and explain the gap. If none was
found, say so plainly.>

## Task definition

- Format: <single-turn / multi-turn / agentic / multimodal>
- Scenario boundaries: <specialty, acuity, setting>
- Exclusions: <explicit list>
- Input modality: <text / image / multi>
- Temporal scope: <vintage of reference material>
- Grounding: <closed-book / open-book with sources>

## Data

- Source: <institution, dataset name, access path>
- Legal basis: <from `compliance-scope.md`>
- Data custodian: <name / role>
- De-identification: <by whom, verified how> (ARISEKit does not own)
- Sampling strategy: <from `implementation-plan.md`>
- Snapshot and version: <item set hash or version pin>
- Subgroup representation: <table or pointer to datasheet>

## Rubric and scoring

- Paradigm: <exact match / reference / rubric / LLM-as-judge /
  expert concordance / agentic pass-at-N>
- Dimensions: <list with weights>
- Aggregation: <mean / min / weighted / per-dimension reporting>
- Judge design: <model, prompt version, visibility settings>
- Concordance with human panel: <metric and threshold>
- Refusals: <counted as ... >
- Abstentions: <counted as ...>
- Format errors: <handled by ...>

## Expert panel

- Size: <N raters>
- Credentials: <board certification, years, subspecialty>
- COI screening: <policy applied, disclosures captured>
- Training: <synchronous / async / worked examples>
- Calibration: <gold-set IRR>
- Working IRR: <metric, threshold, actual>
- Adjudication: <who, how disagreements resolved>

## Model set and inference config

| Model            | Provider  | Version pin | Temperature | Trials per item |
| ---------------- | --------- | ----------- | ----------- | --------------- |
| <model>          | <...>     | <...>       | <...>       | <...>           |
| <baseline>       | n/a       | n/a         | n/a         | n/a             |

- Run manifest: <path>
- Library version: `arisekit` <version from VERSION>
- API call count: <from manifest>
- Cost: <from manifest>

## Results

- Headline metric: <number, CI, definition>
- Per-dimension breakdown: <table or pointer>
- Subgroup slices: <table or pointer>
- Baselines: <non-model baseline numbers for sanity>
- Confidence intervals: <method, e.g. bootstrap N>

## Error analysis

<Qualitative categories of failure. Representative items redacted
to the compliance scope's PHI boundary. Tie each category to a
specific dimension of the rubric where possible.>

## Limitations

<At least three specific reviewer objections, each answered.
Template prompts:>

1. **Panel size.** <Why N raters was defensible given the power
   analysis; what a larger panel would or would not change.>
2. **Contamination.** <What the scan showed; what known leaks
   were excluded; what residual risk remains.>
3. **Rubric bias.** <IRR evidence; how the rubric was piloted and
   revised; what the irreducible disagreement rate is.>
4. <Optional additional limitations specific to this benchmark.>

## Ethics statement

- IRB status: <exempt / approved / not required, per
  `compliance-scope.md`>
- DUA terms relevant to redistribution: <summary>
- Rater compensation: <from `study-plan.md`>
- Consent: <if applicable>

## Reproducibility and datasheet

- Datasheet: <path or "not yet generated; run `arisekit datasheet
  <slug>`">
- Item set hash: <from snapshot policy>
- Rubric version: <pinned>
- Judge prompt version: <pinned>
- Run manifest: <path>

## Submission and release posture

- Release model: <open / held-out / tiered / time-limited, from
  `implementation-plan.md`>
- Held-out items: <N, for leaderboard integrity>
- Access policy: <who can request, how, for what>
- Submission portal: <URL or "pending via MAST CUJ 13">

## Authors and contributions

<CRediT-style: conceptualization, methodology, data curation,
investigation, formal analysis, writing - original draft, writing -
review & editing, supervision, funding acquisition.>

## Funding and conflicts

- Funding: <grant numbers, sponsors>
- Conflicts of interest: <from `study-plan.md` rater disclosures
  and author disclosures>

## Citation and submission

- Target venue: <preprint (arXiv / medRxiv) | peer-reviewed journal
  (name) | workshop | MAST submission>
- Format notes: <venue-specific shape: word count, figure count,
  supplementary limits>

## User confirmation

<Verbatim from the user: "Yes, I am willing to sign my name to
this writeup, these headline claims, these limitations, and this
author list." Date and timestamp.>

## Next step

If preparing for circulation: share `writeup.md` with co-authors,
gather comments, revise.

If preparing for submission: tighten the sections the target venue
specifies, export to the venue's format, and submit.

If preparing for MAST contribution: follow CUJ 13 when it ships;
the writeup is one of the materials reviewers will read.

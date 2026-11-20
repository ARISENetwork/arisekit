---
name: arisekit/existing-benchmark-search
description: Checks whether an existing public or MAST medical AI benchmark already covers the user's need before they build a new one. Stage 2 of the ARISEKit pipeline. Invoked after `arisekit/needs-analysis`. Produces `existing-coverage.md`. If a match is found, this skill recommends stopping the pipeline early.
---

# Existing-benchmark search

You are stage 2 of the ARISEKit benchmark pipeline. The user just
produced `need-statement.md` in stage 1 (`arisekit/needs-analysis`).
Before helping them build a new benchmark, check whether one that
fits their need already exists. The best benchmark is sometimes the
one the user does not build.

## Recognize existing MAST benchmarks

Read the [MAST recognition reference](catalog/mast-benchmarks.md) before responding to a named
benchmark. Use its aliases and task patterns from the first turn. Carry the
chosen family and requested adaptation forward; clarify a changed family
without asking the user to define known acronyms.

When a family was selected in the benchmark chooser, review whether that
family already covers the clinical scope and adaptation established in stage
1. Do not reopen family selection or recommend stopping merely because the
selected parent benchmark exists. Identify the actual coverage or gap; a
specialty or healthcare-system extension may continue with the parent family
retained. Recommend using the existing benchmark when it covers the stated
need without that adaptation, and preserve the user's decision.

## What you produce

A single markdown file, `existing-coverage.md`, using
[`templates/existing-coverage.template.md`](templates/existing-coverage.template.md).

The file must capture:

- **Need summary.** A tight paraphrase of `need-statement.md`'s
  problem, population, and outcomes.
- **Search sources.** Every catalog or index you queried, with
  last-updated timestamps.
- **Candidate matches.** Ranked list of existing benchmarks that
  plausibly cover the need, each with:
  - Name, home URL, MAST status (member / adjacent / external).
  - Confidence (low / medium / high) with a 1-2 sentence rationale
    tied back to the need statement.
  - Access requirements (public / gated / institutional).
  - The command or snippet to run the match via ARISEKit, if
    applicable.
- **Recommendation.** One of:
  - `stop` - a high-confidence match exists and the user should
    use it instead of building.
  - `continue` - no match, or matches are too weak; proceed to
    `arisekit/compliance-intake`.
  - `continue-with-note` - a match exists but the user has a
    defensible reason to build anyway (specialty nuance, access
    gap, novel population). Record the reason.
- **User decision.** Verbatim. If they accept the match, capture
  how they will run it. If they override, capture why.

## How to run the conversation

1. Read `need-statement.md`. Quote its problem, population, and
   outcomes fields back to the user to confirm you captured them.
2. Query your catalog. For the initial release, include at least:
   - The current MAST benchmarks: First Do NOHARM, SCT-Bench,
     MedAgentBench, ReXrank Mini, CPC-Bench.
   - A curated list of public medical AI benchmarks (HealthBench,
     MedHELM, MedQA, MedAlign, OpenEvidence-adjacent evals,
     Doximity eval if public, etc.). This list lives in
     [`catalog/public-benchmarks.md`](catalog/public-benchmarks.md).
3. Present the top candidates conversationally, one at a time.
   State your confidence and *why*, citing the need statement.
4. Let the user reject, accept, or ask for the next candidate.
5. On acceptance, write `existing-coverage.md` with recommendation
   `stop` and the run snippet. Suggest handing off to
   [run configuration](../run-config/SKILL.md)
   so the user can run the existing benchmark against the models
   they care about.
6. On rejection of all candidates, write `existing-coverage.md`
   with recommendation `continue` (or `continue-with-note` if the
   user cites an existing-but-insufficient match), and hand off
   to `arisekit/compliance-intake`.
   If the search yields no plausible candidate at all, write "No
   plausible matches were found in the dated sources above" in the
   Candidate matches section. Do not invent a placeholder candidate.

## Do

- Be honest about confidence. "High" should mean the match clearly
  covers the need; "medium" means it overlaps but may miss a
  dimension; "low" is a courtesy mention.
- Name the specific dimension that makes a match imperfect
  (population, modality, scoring style, access).
- Time-stamp the catalog. If a source is older than 6 months,
  call that out.
- When multiple matches overlap, explain what each covers vs
  misses; do not try to pretend there is one obvious answer.

## Do not

- Do not rubber-stamp a new benchmark when a high-confidence match
  exists. Surface the match loudly; the user can still override,
  but they should see the recommendation.
- Do not silently drop candidates the user has not seen.
- Do not guess about access. If you cannot tell whether the user
  can actually run a match, mark access as "unknown - verify with
  source" rather than assuming.
- Do not run multiple stages. This skill does coverage search only.
- Do not require a local checkout or run command for a rejected candidate.
  When continuing to build, the official source link is sufficient for
  First Do NOHARM. Include its checked-in launcher when recommending that
  the user stop and run it. Any commands supplied must still be valid.

## Exit

- Recommendation `stop`: write `existing-coverage.md`, close the
  pipeline cleanly, and tell the user which CUJ / skill to follow
  to actually run the matched benchmark.
- Recommendation `continue` or `continue-with-note`: write
  `existing-coverage.md`, hand off to `arisekit/compliance-intake`.

## Upstream artifacts

- `need-statement.md` (required).

## Downstream readers

- `compliance-intake` and later skills cite `existing-coverage.md`
  when the user chose to continue despite an existing match.
- `implementation-plan` includes the recommendation and any
  override rationale so reviewers see the decision trail.

## Catalog maintenance

The catalog under `catalog/` is hand-maintained. PRs welcome. Keep
entries terse: name, URL, MAST status, modality, scoring pattern,
access notes, last-verified date.

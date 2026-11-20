# Benchmark governance spec

_Author:_ <primary author>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/governance-spec`
_Upstream:_ [`need-statement.md`](need-statement.md),
[`existing-coverage.md`](existing-coverage.md),
[`compliance-scope.md`](compliance-scope.md),
[`data-profile.md`](data-profile.md),
[`rubric.md`](rubric.md),
[`study-plan.md`](study-plan.md),
[`implementation-plan.md`](implementation-plan.md),
[`writeup.md`](writeup.md), run manifest: <path>

This document records this benchmark's governance position. Sections
covering pipeline tasks #106-#111 are co-owned with MAST: where MAST
publishes a canonical governance spec, this document states whether
this benchmark adopts it verbatim or diverges. Section #117 is this
benchmark's own retirement policy and is fully the author's call.

## Submission spec

_Pipeline task:_ #106
_Stance vs MAST canonical spec:_ <adopt verbatim | diverge | proposal
pending MAST response>

- Scorer interface: <class path and `build()` factory signature, from
  `implementation-plan.md`>
- Item schema: <required `BenchmarkItem` slots and metadata fields>
- Metadata required per item: <subgroup labels, provenance, snapshot
  version, rubric version>
- Output schema contract: <raw JSONL shape, compiled CSV shape, score
  column naming>
- Divergence justification (if any): <one paragraph; omit if adopting
  MAST default>

## Review process and reviewer pool

_Pipeline task:_ #107
_Stance vs MAST canonical spec:_ <adopt verbatim | diverge | proposal
pending MAST response>

- Who reviews a model submission: <pool composition, minimum reviewer
  count, specialty match requirement>
- How review is solicited: <standing pool | per-submission invite |
  MAST-managed>
- Decision criteria: <the rubric reviewers apply, beyond the scorer's
  numeric output>
- Anti-rubber-stamp controls: <blinding, author-recusal, quorum rules,
  disagreement adjudication>
- Author COI declaration: <the benchmark author's relationship to
  submissions from their own lab or institution, and how that is
  handled>
- Divergence justification (if any): <omit if adopting MAST default>

## Appeals process

_Pipeline task:_ #109
_Stance vs MAST canonical spec:_ <adopt verbatim | diverge | proposal
pending MAST response>

- What a rejected submitter can do: <request clarification | request
  re-review with new evidence | escalate>
- Timeline: <days from rejection notice to appeal filing, days to
  response>
- Escalation path: <to whom, with what threshold>
- Evidence requirements: <what a successful appeal must show>
- Divergence justification (if any): <omit if adopting MAST default>

## Deprecation process

_Pipeline task:_ #110
_Stance vs MAST canonical spec:_ <adopt verbatim | diverge | proposal
pending MAST response>

- Triggers for deprecation: <invalidated data, broken scorer, loss of
  custodian, regulatory change>
- Notice period before removal: <days or weeks>
- Communication channel: <MAST changelog | mailing list | leaderboard
  banner>
- Archival policy: <what is preserved, where, for how long>
- Leaderboard handling: <frozen snapshot | removed entirely | marked
  historical>
- Impact on downstream integrations: <what consumers need to do>
- Divergence justification (if any): <omit if adopting MAST default>

## Tiering criteria

_Pipeline task:_ #111
_Stance vs MAST canonical spec:_ <adopt verbatim | diverge | proposal
pending MAST response>

- Current claimed tier: <toolkit-produced | MAST-compatible |
  MAST-canonical>
- Evidence supporting the claimed tier: <pointers to upstream
  artifacts and run outputs>
- Promotion gap to the next tier (if applicable): <the specific work
  that would move this benchmark up one tier>
- Tier definitions this benchmark is using:
  - Toolkit-produced: <definition adopted or proposed>
  - MAST-compatible: <definition adopted or proposed>
  - MAST-canonical: <definition adopted or proposed>
- Divergence justification (if any): <omit if adopting MAST default>

## Retirement criteria

_Pipeline task:_ #117
_Scope:_ this benchmark only. Not a negotiation with MAST; the
author's own sunset policy.

- Saturation trigger: <e.g. "top-3 model accuracy exceeds 0.95 on the
  held-out set for two consecutive quarters">
- Contamination trigger: <the standing-cadence scan finding that
  would force retirement rather than refresh; cite the contamination
  posture from `data-profile.md`>
- Obsolescence trigger: <clinical guideline change, modality shift,
  or scope change that makes the benchmark no longer reflect the
  need statement>
- Successor trigger: <existence of a named successor benchmark that
  covers the same need more rigorously>
- Decision authority: <who calls retirement; author, MAST curators,
  or joint>
- Sunset communication: <how retirement is announced to leaderboard
  consumers and downstream integrations>
- Retention after sunset: <what artifacts remain accessible: items,
  rubric, writeup, run manifest, leaderboard snapshot>

## User confirmation

<Verbatim from the user: "Yes, I am willing to be held to these
governance commitments for this benchmark, including the retirement
criteria, and the adopt-or-diverge statements above are accurate."
Date and timestamp.>

## Next step

Submit `governance.md` alongside `writeup.md` to MAST curators as
part of the benchmark submission package. Sections marked "proposal
pending MAST response" will be reconciled against MAST's canonical
governance spec during curator review.

If tier promotion to canonical is the stated goal, the promotion gap
recorded in the tiering section is the explicit list of work that
closes it; follow CUJ 13 when it ships.

# Need statement

_Author:_ P0 golden-path fixture owner  
_Date:_ 2026-09-02  
_Produced by:_ `arisekit/needs-analysis`  
_Status:_ accepted

## Problem

Clinical benchmark authors need a small end-to-end contract example that starts with reviewed planning artifacts and ends with verifiable run evidence. Without it, repository changes can break materialization, structural validation, or result inspection before an author reaches real benchmark work.

## Population

In scope:

- ARISEKit benchmark authors testing the local text-only scaffold.
- Two wholly synthetic outpatient-routing cases used only as contract fixtures.

Out of scope:

- Real patients, patient records, protected health information, and clinical deployment.
- Claims about a model's clinical accuracy, safety, or generalization.

## Current state

Maintainers test scaffold components separately and inspect generated files manually. A failure is observed as a missing artifact, stale digest, incompatible package, failed smoke run, or unverifiable result bundle.

## Opportunity

A checked-in fixture can bind accepted authoring outputs to a deterministic source, strict package, local stub run, and hashed evidence. The model-like route is useful only because it exercises the same runner path without inference or network access.

## Outcomes

- The seven accepted planning artifacts and source bytes pass exact SHA-256 verification.
- `new-benchmark`, linked-provenance `check-benchmark`, and the planned `stub/reference` smoke run succeed in sequence.
- `run-results.json` verifies its raw checkpoint and score CSV, and the runnable manifest reaches `ready`.

## Non-goals

- Evaluate clinical reasoning, triage quality, or patient outcomes.
- Establish dataset representativeness, privacy certification, publication readiness, or MAST admission.
- Authorize any external model provider or any data other than the two checked-in synthetic rows.

## Defensibility

**Target reviewers and venues.**

- Primary venue: ARISEKit repository regression review.
- Fallback venue: an ARISEKit or MAST integration workshop demonstration.
- Reviewer pool this implies: benchmark engineers plus a clinician reviewer who confirms the synthetic, non-clinical claim boundary.

**Predictable objections.**

- Two trivial cases cannot support a clinical-performance claim; no such claim is made.
- `stub/reference` sees the ground truth; it is used only to test plumbing.
- Synthetic routing text does not represent clinical populations; population generalization is out of scope.

**Representativeness defense.**

- Subgroups that must be present for the claim to survive: one emergency-route label and one routine-route label.
- Minimum representation the benchmark will not ship below: one row in each fixture cell, two rows total.
- Known gaps in the planned sample: no real patients, demographic variation, uncertain cases, or clinical adjudication.
- One-line defense: the claim concerns deterministic software integration, not clinical population performance.

**Weakest upstream claim.**

- Section most at risk: Opportunity.
- Why it is the weakest: the stub proves path integration but cannot show useful model behavior.
- How downstream skills should compensate: every artifact, report, and README must repeat the plumbing-only claim boundary.

**"Nobody cites this" failure mode.**

- Fixture-owner statement: "This would be useless if anyone mistook it for clinical evidence."
- What must be true upstream: the source must remain wholly synthetic, the route must remain local, and all acceptance checks must be structural.

## One-breath summary

"Build one tiny public synthetic benchmark that proves the accepted ARISEKit plan can become a runnable, self-verifying package without making a clinical claim."

## Open questions

- None for this fixture. Any clinical-content or external-provider use requires a new need analysis and authorization record.

## Next stage

`arisekit/existing-benchmark-search` (checks whether a public or MAST benchmark already covers this need).

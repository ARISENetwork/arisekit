# Study plan

_Author:_ P0 golden-path fixture owner  
_Date:_ 2026-09-02  
_Produced by:_ `arisekit/study-design`  
_Upstream:_ [`need-statement.md`](need-statement.md), [`existing-coverage.md`](existing-coverage.md), [`compliance-scope.md`](compliance-scope.md), [`data-profile.md`](data-profile.md), [`rubric.md`](rubric.md)  
_Status:_ accepted

## Panel size

- Number of raters (N): 0.
- Floor justification: N/A; the fixture labels are pre-scored and no human annotation or concordance claim is in scope.
- Inter-rater reliability threshold this N is defended against: N/A.
- Attrition floor: N/A; there is no panel.
- Reviewer-objection defense: this fixture makes no rater-concordance or clinical-validity claim, so a panel would not answer its software-contract question.

## Credentials

- Specialty floor: N/A.
- Years-of-practice floor: N/A.
- Subspecialty / fellowship floor: N/A.
- Board-certification requirement: N/A.
- Encoded biases the user accepts: N/A for a panel; the synthetic routing language reflects the fixture author's wording and is not clinically validated.
- Recruiting feasibility check: N/A; no raters are recruited.
- Recruitment plan: N/A; no compensation.
- "Expert" defined as, for this benchmark: N/A; the fixture does not use or claim expert judgment.

## Conflict-of-interest screening

- Written policy: N/A because no rater sees or scores an item. Any future human annotation requires a new study plan and conflict policy before work begins.
- Conflict categories evaluated:
  - Affiliation with an evaluated model vendor: N/A; no evaluated provider model.
  - Authorship of a competing benchmark: N/A.
  - Sponsor employment or grant support: N/A.
  - Equity, consulting, or advisory-board relationships with a vendor whose model is evaluated: N/A.
  - Relationship to the data-producing institution: N/A; no institution produced data.
  - Other: N/A.
- Disclosure instrument: N/A.
- Adjudicator for borderline disclosures: N/A.
- Exclusion trigger: N/A.
- Pre-annotation check for undisclosed conflicts: N/A.
- Disclosures captured for the writeup: N/A; record that no rater panel or provider model was used.

## Per-item coverage

- Design: pre-scored synthetic reference label; one deterministic stub response per item.
- Rationale tied to the rubric and panel size above: exact-match plumbing needs one frozen reference, not a clinical panel.

## Concordance plan

- Metric(s): N/A.
- Threshold for keeping an item: N/A; both source rows are retained when schema and scorer validation pass.
- Threshold for dropping or re-rating an item: N/A; invalid rows fail scaffolding instead of entering adjudication.
- Reporting: state that concordance was not measured and that accuracy 1.0 is expected from the reference stub.

## Calibration pass

- Anchor items: N/A.
- Training round: N/A.
- Drift monitoring: N/A; deterministic source and scorer hashes detect changes.

## Frozen annotation methodology contract

N/A. Human annotation is not in scope, so there is no `annotation-study-policy.json`, policy digest, rater population, credential requirement, panel size, calibration policy, IRR method or threshold, adjudication policy, or annotation change rule.

## Edge cases and adjudication rules

| Edge case | Adjudication rule |
| --- | --- |
| Response contains explanation or wrong-case label | score 0 under the frozen case-sensitive exact-match rubric |
| Missing response or terminal runner error | fail the smoke acceptance check; do not reinterpret the item |
| Duplicate id, missing mapped field, or stale source hash | stop during scaffold validation before a run |
| Proposed clinical-content correction | N/A to this accepted version; create a new reviewed artifact and source version |

## Taxonomy / sub-scores

| Category | Definition | Assignment rule |
| --- | --- | --- |
| `emergency-route-label` | synthetic prompt whose preassigned answer is emergency evaluation | `reference_answer == "B"` in item `synthetic-routing-001` |
| `routine-route-label` | synthetic prompt whose preassigned answer is routine follow-up | `reference_answer == "A"` in item `synthetic-routing-002` |

Only `overall/accuracy` is reported; category rows describe fixture coverage and are not clinical sub-scores.

## NOHARM-style review topology

N/A. `rubric.md` chose MCQ / fixed-answer. Named clinical locks, derivative families, three-family fixtures, and parity campaigns do not apply.

## Rater tooling

- Current plan: N/A - pre-scored JSONL with no rater interface.
- Gaps: none for the accepted non-annotation workflow.

## Timeline and budget

- Hours per rater: N/A; 0 raters.
- Total rating time: 0 hours.
- Wall-clock: less than one minute for local scaffold, check, and smoke on a typical development machine.
- Budget: USD 0.00 for the `stub/reference` route.

## Validity risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Non-representative rater panel | N/A; no panel and no concordance claim |
| Item selection bias | publish both synthetic rows and limit the claim to contract coverage |
| Rater drift over time | N/A; hashes freeze source, prompt, and scorer inputs |
| Test-retest instability | use deterministic `stub/reference`, one trial, and exact-match scoring |
| Perfect score misread as clinical evidence | repeat the plumbing-only boundary in artifacts, generated README, and run report |

## Next stage

`arisekit/implementation-plan` (synthesizes all upstream artifacts into an implementation plan a coding agent can build against). Annotation-task design is N/A because annotation is not required.

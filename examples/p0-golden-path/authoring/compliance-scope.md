# Compliance scope

_Author:_ P0 golden-path fixture owner  
_Date:_ 2026-09-02  
_Produced by:_ `arisekit/compliance-intake`  
_Upstream:_ [`need-statement.md`](need-statement.md), [`existing-coverage.md`](existing-coverage.md)  
_Status:_ accepted

## Jurisdiction

- Primary regulatory regime: N/A - no human data or institutional health record is used.
- Institution(s): N/A - repository-owned synthetic fixture.
- Distribution: public benchmark fixture.

## Data class considered

| Class | Viable for this benchmark? | Notes |
| --- | --- | --- |
| Fully synthetic | yes | Selected; both rows were written for this fixture. |
| Fully de-identified | no | N/A; using patient-derived data would expand the approved scope. |
| Limited dataset | no | N/A; no DUA or institutional extract is authorized. |
| Identifiable | no | Prohibited for this fixture. |

**Recommended posture:** fully synthetic, public, and limited to the exact checked-in bytes.

## IT request specification (hand this to your IT department)

- **Cohort.** Two fictional outpatient-routing prompts; no patient cohort.
- **Time window.** N/A - no clinical events were extracted.
- **Fields required.** `case_id`, `prompt`, `reference_answer`, and `setting`.
- **Format expectation.** UTF-8 JSONL, one record per item.
- **De-identification method.** Synthetic generation; de-identification is N/A because no source record exists.
- **Estimated volume.** 2 items.
- **Notes.** Do not replace these rows with patient-derived examples under this authorization.

## Rater / human-subjects scope

- Rater inputs contain: N/A - the two labels are pre-scored fixture data.
- Rater workflow: N/A - no human annotation occurs.
- Implications: IRB, privacy-office review, and DUA are not needed for this exact synthetic fixture; any human-subjects or patient-data use requires a new review.

## Model-provider compatibility

| Planned provider | Compatible with data class? | Alternative if not |
| --- | --- | --- |
| Local `stub/reference` | yes - reads local synthetic references and makes no provider call | N/A |
| External provider | not authorized | complete a new route and egress review |

## Approvals checklist

- [x] IRB review - not needed for the exact synthetic, non-human-subjects fixture.
- [x] Institutional privacy office sign-off - not needed; no institutional or patient data.
- [x] Data Use Agreement - not needed; source text is original fixture content.
- [x] Model-provider Business Associate Agreement - not needed; no PHI and no external provider.
- [x] Other: fixture owner approved public release and deterministic materialization of the exact two rows.

## Licensing and redistribution

### Sources by license

| Source | License or agreement | Redistribution terms (plain language) | Clause or URL evidence |
| --- | --- | --- | --- |
| `cases.synthetic.jsonl` | original repository fixture text | public repository redistribution and derivative package materialization are approved | materialization authorization in `benchmark-build-spec.json` |

### Redistribution posture

- **Selected posture:** open, represented as `public` in the build sidecar.
- **Forced by:** no external restriction; posture reflects the fixture owner's authorization.
- **Rationale:** original synthetic text can be checked in with its generated package and local smoke evidence.

### Blocking clauses

| Source | Clause (quote or paraphrase with citation) | What it blocks |
| --- | --- | --- |
| `cases.synthetic.jsonl` | N/A - no third-party license or agreement | nothing within this exact fixture scope |

### Downstream implications

- **`implementation-plan` inputs.** Release model: open/public. Held-out item count: 0. Access policy: public repository access. Item lifetime: indefinite unless maintainers replace the versioned fixture.
- **`release-writeup` inputs.** Ethics summary: wholly synthetic original text with no human-subjects data. Submission-and-release posture: public fixture; no clinical-performance or privacy-certification claim.
- **Open items.** None.

## Blockers

None for the exact checked-in source, local stub route, public package, and retained evidence. Any other data or provider is blocked pending a new review.

## Next stage

`arisekit/data-intake` (inspects a sample file and profiles format, structure, and eval-pattern fit).

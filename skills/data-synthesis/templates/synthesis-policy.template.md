# Synthesis policy

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/data-synthesis`
_Batch ID:_ <slug or uuid>
_Policy version:_ <v1, v2, ...>
_Upstream:_ [`data-sources.md`](data-sources.md) (if applicable),
[`rubric.md`](rubric.md)

## Synthesis rationale

<One paragraph: why this batch needs synthesis. Cite the coverage
gap from data-sources.md, the consent / PHI constraint, or the
counterfactual goal.>

## Seed schema

| Field | Type | Allowed values / range | Required? | Notes |
| ----- | ---- | ---------------------- | --------- | ----- |
| age | integer | 18-95 | yes | adult cohort |
| sex | enum | female, male | yes | |
| encounter_type | enum | inpatient, outpatient, ED | yes | |
| chief_complaint | string | <bounded vocabulary or open> | yes | |
| expected_answer_shape | enum | free-text, structured, Likert | yes | matches rubric |
| <field> | <type> | <range / set> | <yes/no> | <notes> |

## Plausibility constraints

```yaml
# YAML block authored by the user. Embedded verbatim in the
# generation prompt and reused for plausibility scoring. Every rule
# must be concrete enough to be checked mechanically.

physiological_ranges:
  hemoglobin_g_dl:
    adult_male: [13.5, 17.5]
    adult_female: [12.0, 15.5]
  # ...

medication_diagnosis_coherence:
  - if_condition: heart_failure
    expect_medication_class_at_least_one_of:
      - ACE_inhibitor
      - ARB
      - ARNI
  # ...

age_appropriate_presentations:
  - condition: appendicitis
    age_range: [5, 80]
  # ...

contraindications:
  - drug: NSAID
    avoid_if: [CKD_stage_4, CKD_stage_5, active_GI_bleed]
  # ...
```

## Diversity targets

| Axis | Target distribution | Tolerance |
| ---- | ------------------- | --------- |
| encounter_type | inpatient 40%, outpatient 50%, ED 10% | +/- 5% |
| severity | mild 30%, moderate 50%, severe 20% | +/- 5% |
| sex | female 50%, male 50% | +/- 3% |
| <axis> | <distribution> | <tolerance> |

## Scoring configuration

- **Plausibility threshold.** <0.0 - 1.0>; drafts below this are rejected.
- **Rubric source.** [`rubric.md`](rubric.md)
- **Rubric pass threshold.** <0.0 - 1.0>; drafts below this are rejected.
- **Retry budget per under-coverage cell.** <integer draws>

## Budget caps

- **Per-batch draft cap.** <integer>
- **Per-item generation tokens.** <integer>
- **Per-item plausibility scoring tokens.** <integer>
- **Per-item rubric scoring tokens.** <integer>

## Pilot results

| Metric | Value |
| ------ | ----- |
| Drafts attempted | <integer> |
| Drafts accepted | <integer> |
| Acceptance rate | <%> |
| Rejected on plausibility | <integer> |
| Rejected on rubric | <integer> |
| Under-covered cells after pilot | <list> |

**Pilot disposition.** <proceed with full run | adjust constraints and re-pilot | adjust rubric and re-pilot | abandon synthesis>

## Full-run results

| Metric | Value |
| ------ | ----- |
| Drafts attempted | <integer> |
| Drafts accepted | <integer> |
| Acceptance rate | <%> |
| Under-covered cells after run | <list, or "none"> |
| Total cost | <USD or token count> |

## Notes for downstream

<Anything `arisekit/data-item-shape` needs to know about how the
drafts were generated. For example: drafts may carry a `synthesis_notes`
field that should ride through to the BenchmarkItem metadata.>

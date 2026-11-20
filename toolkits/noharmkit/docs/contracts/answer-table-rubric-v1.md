# Rubric contract v1

Reader's guide to the [versioned rubric contract](../../skills/generate-answer-table/contract-v1.md).
The complete rules live there; this guide does not change them. Schema keys and
filenames remain compatible with [Task, Solution, and Case](../../README.md#terminology).
Bundled rules are clinical; structural validation is not clinical acceptance.

## Model

Each Decision is met, partly met, or not met. Omission, residual omission,
relative harm, delay, and harmful recommendations are recorded as separate
events. Headlines are worst harm and severity-weighted F1.

## Stored record

One record per case, containing Decisions and `recommendations` rows scored 1-9:
7-9 appropriate, 4-6 uncertain, 1-3 inappropriate. Highest-scored appropriate
rows are best options. [Fields and authoring rules](../../skills/generate-answer-table/contract-v1.md#stored-record)
cover overrides, timing, equivalents, required parts, and incomplete versions.

- New records default to dual mode (`harmOverrides: true`), separating appropriateness and categorical harm. Combined mode derives harm from scores.
- Each case has one Follow-up Decision (`D1`), a separate return-precautions Decision, and at most two standard additional-care Decisions.
- New rows require descriptive action tags; tags do not change judging or scoring. Legacy untagged records remain valid.
- `usualCare.harm` is required before saving and caps omission harm in dual mode. Usual care means “Continuation of the patient's current management or usual care, without additional input.” It is never scored.
- Activation supports `always`, `onlyIf` with `any`/`all`, and `future`. Omitted `match` means `any`.
- Rows cannot merely restate silence. Store JSON with two-space indentation, preserved Unicode, and a final newline.

## Judge output

The judge maps recommendations to Decision rows, with quoted evidence, required
parts, role, contradiction, unmatched statements, and case-level `offRubric`.
See the [output contract](../../skills/judge-answer-table/rules.md#judge-output)
and [schema](../../skills/judge-answer-table/schema.json).

## Judge rules

Patient-specific actionable recommendations count; rejected options,
nonactionable background, and generic safety-netting do not. Row specifics,
required parts, roles, and provisional unmatched/off-rubric handling follow the
[complete mapping rules](../../skills/judge-answer-table/rules.md#judge-rules).
The judge cannot choose new thresholds or grades.

## Scoring rules, in order

Activation, contradiction, unmatched findings, harmful rows, outcome, then
credit. Met earns 1, partly met earns `rho`, not met earns 0. Conditional branches,
alternatives, fallbacks, partial required parts, and `alsoTakesCareOf` have
specific rules; use the [full ordered contract](../../skills/generate-answer-table/contract-v1.md#scoring-rules-in-order).
Do not infer these from the summary.

## Metrics

Default candidate weights: uncertain 1, mild 3, moderate 24, severe 72. Freeze
weights before comparison. [Exact metric definitions](../../skills/generate-answer-table/contract-v1.md#metrics):

| Metric | Meaning |
| --- | --- |
| Worst harm | Most severe event; report its distribution across responses |
| Recall | Severity-weighted credit for addressing active needs |
| Precision | Credit for appropriate recommendations relative to recommended harm |
| F1 | `2PR / (P + R)`, zero when both are zero |

No-omission-harm Decisions catch harmful recommendations without adding recall
credit. Provisional findings keep headlines provisional. Event counts are
diagnostic and can describe overlapping harms; do not sum them into a harm score.

## Implementation limits

[Scorer](../../tools/score_answer_table.py),
[editor types](../../app/lib/answer-table.ts), and versioned contracts define
behavior. Format checks establish neither judge accuracy nor clinical validation.
See [evidence rules](../PROJECT_CHARTER.md#evidence-and-reporting).

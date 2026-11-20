# Data profile

_Author:_ P0 golden-path fixture owner  
_Date:_ 2026-09-02  
_Produced by:_ `arisekit/data-intake`  
_Upstream:_ [`need-statement.md`](need-statement.md), [`existing-coverage.md`](existing-coverage.md), [`compliance-scope.md`](compliance-scope.md)  
_Status:_ accepted and materialized

## Provisional?

- [ ] Yes - N/A; the source exists.
- [x] No - this profile reflects the exact checked-in synthetic sample.

## Source

`cases.synthetic.jsonl`, written as original synthetic fixture content by the P0 golden-path fixture owner. It is not derived from a patient, clinical record, publication, or external benchmark.

## Named-archetype request

- User's words: N/A.
- Candidate archetype: N/A.
- Requested aspects: N/A.
- Status: N/A; the fixture uses the generic text scaffold and fixed-answer scorer.

## Source ledger and draft lineage

| Source id | Title / locator | Rights basis | Rights note / terms | Recorded by / at | SHA-256 or pending | Release scope / authorization | Proposed blueprint fields |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `p0-synthetic-source` | `cases.synthetic.jsonl` | original | wholly synthetic repository fixture; no third-party terms | P0 golden-path fixture owner; 2026-09-02T12:05:00Z | `d5ebf0dadd7c0b1f3974ff804862e006614529fa159ab92e1d3bda804c03ebff` | public; authorization-text SHA-256 `463b3069f8d1dde5b1ab27531992a993cb7b626e59132a7d8fb9b088a93104e9`; fixture owner; 2026-09-02T12:05:00Z | N/A - no blueprint |

- Rights owner or institutional decision-maker: P0 golden-path fixture owner.
- Sources with `rights_basis: unknown`: none.
- Sources without a complete release authorization: none.
- Package-ready export blocked on: none.

## Volume

- Items in sample: 2.
- Planned total items: 2.
- Per-field size distribution: short identifiers and labels, one short synthetic vignette per row, and one short metadata value.

## Shape

| Field | Type | Semantic role | Notes |
| --- | --- | --- | --- |
| `case_id` | string | unique `BenchmarkItem.id` | two unique stable ids |
| `prompt` | string | `BenchmarkItem.prompt` | synthetic case plus labeled routes |
| `reference_answer` | string | `BenchmarkItem.ground_truth` | exactly `A` or `B` in this fixture |
| `setting` | string | `BenchmarkItem.metadata.setting` | `synthetic-outpatient-routing` |
| attachments | list of path | `BenchmarkItem.attachments` | N/A; build-spec value is `null` and normalized list is empty |

## Modality

- Text.
- If multimodal: N/A - no images or attachments.
- If agentic: N/A - no tools or environment.

## Ground-truth structure

Each item has one reviewer-assigned label from `A`, `B`, or `C`. The scaffold maps `reference_answer` to `ground_truth`; exact-match scoring compares the stripped response case-sensitively.

## Quality red flags

- [ ] Duplicate `id`s - none.
- [ ] Empty `prompt` or `ground_truth` - none.
- [ ] Suspicious label distribution - N/A for a two-cell plumbing fixture; the labels are intentionally one `A` and one `B`.
- [ ] Possible PHI remnants - none; the rows are original synthetic text.
- [ ] Test/train leakage risk - N/A to clinical evaluation; `stub/reference` intentionally reads ground truth for contract testing.
- [ ] Other - none.

## Eval-pattern candidates (hand-off to `arisekit/rubric-design`)

| Pattern | Plausibility | Why / why not |
| --- | --- | --- |
| LLM-as-judge rubric | no | subjective judging would add cost and variance without testing more plumbing |
| Expert-panel concordance | no | labels are pre-scored and no human-study claim is in scope |
| Pass@1 agentic / tool calling | no | no tools or environment exist |
| Multimodal LLM judge | no | source is text-only |
| Structured diagnostic accuracy | medium | single labels fit structured accuracy, but the prompts are routing-contract fixtures rather than diagnostic cases |
| MCQ / fixed-answer | yes | one reference label maps directly to the built-in exact-match primitive |

## Data origin

- [ ] Pure real.
- [x] Pure synthetic.
- [ ] Hybrid (real plus synthetic).

The synthetic-only choice follows `compliance-scope.md` and keeps patient data, identifier clearance, and provider disclosure outside the fixture.

## Hybrid mix defense

- Origin status: N/A: pure synthetic.
- Skip rationale: no real items are used, so there is no hybrid fraction to defend.

### Fraction

N/A - 0 real items, 2 synthetic items, 2 total, 0% real, and 100% synthetic. Real-budget ceiling, mix power analysis, and hybrid allocation are not applicable.

### Per-subgroup or per-task-type mix

N/A - the two fixture cells each contain one synthetic item; there is no mixed-origin cell.

### Distribution-skew validation

N/A - there are not two origins to compare. No distributional or clinical-generalization claim is made.

### Rationale

N/A as a hybrid defense. Pure synthetic origin is required by the compliance scope and plumbing-only claim.

### Reviewer-objection answer

"There is no synthetic-half contamination question because the entire fixture is synthetic and no clinical conclusion is drawn."

## Fit check against the need statement

The accepted outcomes are:

> The seven accepted planning artifacts and source bytes pass exact SHA-256 verification; `new-benchmark`, linked-provenance `check-benchmark`, and the planned `stub/reference` smoke run succeed in sequence; and `run-results.json` verifies its raw checkpoint and score CSV while the runnable manifest reaches `ready`.

The four-field JSONL shape supports all three outcomes. It does not support clinical-performance outcomes, which are explicit non-goals.

## Blockers

None. Any patient-derived replacement, attachment, non-text modality, or external route would invalidate this profile and return the work to compliance intake.

## Next stage

`arisekit/rubric-design` (pick the scoring pattern and map it to an ARISEKit library primitive).

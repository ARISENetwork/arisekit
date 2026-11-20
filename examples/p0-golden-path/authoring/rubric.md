# Rubric

_Author:_ P0 golden-path fixture owner  
_Date:_ 2026-09-02  
_Produced by:_ `arisekit/rubric-design`  
_Mode:_ benchmark  
_Upstream:_ `need-statement.md`, `existing-coverage.md`, `compliance-scope.md`, `data-profile.md`  
_Status:_ accepted

## Chosen pattern

- [ ] LLM-as-judge rubric.
- [ ] Expert-panel concordance.
- [ ] Pass@1 agentic evaluation.
- [ ] Multimodal LLM-as-judge.
- [ ] Structured diagnostic accuracy.
- [x] MCQ / fixed-answer.
- [ ] Custom.

## Rationale

Each synthetic row has one reviewer-assigned label, and the need concerns deterministic integration rather than subjective clinical quality. Fixed-answer scoring is sufficient, reproducible, offline, and directly supported by the source shape.

## ARISEKit library primitive

- Primitive(s): `arisekit.scorer.exact_match`.
- Status: exists.
- If new primitive needed: N/A; the v1 scaffold has a deterministic exact-match adapter.

## Scoring definition

- Dimensions / sub-scores: one `accuracy` dimension with weight 1.0.
- Normalization: strip leading and trailing whitespace; preserve case.
- Item score: 1 when the normalized response exactly equals `ground_truth`; otherwise 0.
- Aggregate: arithmetic mean across the two item scores, reported as `overall/accuracy` with `n=2`.
- Judge prompts: N/A; no judge model is used.
- Concordance formula: N/A; no expert panel is used.
- Pass/fail predicates: the smoke contract passes when 2 calls complete, 0 terminal errors occur, and accuracy is 1.0.
- Anchor examples: response `B` against reference `B` scores 1; response `b`, `B.`, or `A` against reference `B` scores 0.
- System prompt: `Return only the single reference label: A, B, or C.`

## NOHARM-style contract

N/A. The chosen pattern is MCQ / fixed-answer, not NOHARM-style. Response, action-rubric, selection-group, specialist-consult, matching-guidance, judge, and NOHARM aggregation contracts do not apply.

## Known biases / trade-offs

- `stub/reference` intentionally receives each ground truth, so a perfect score proves only runner and scorer plumbing. Mitigation: every artifact and report states this boundary.
- Two simple labels cannot estimate reliability, subgroup performance, or clinical validity. Mitigation: no such metric or claim is reported.
- Case-sensitive exact match rejects explanatory text. This is intentional because the system prompt freezes a single-label response contract.

## Alternatives considered

- LLM-as-judge - rejected because it adds provider access, cost, and nondeterminism without strengthening a plumbing proof.
- Expert-panel concordance - rejected because the labels are pre-scored and no human study is in scope.
- `arisekit.scorer.choice` - rejected because exact match directly implements the frozen single-label contract without an additional choice-extraction rule.

## Cost implications

- Per-item judge calls: 0.
- Judge model(s): N/A.
- Rough per-item cost estimate: USD 0.00 with `stub/reference`.
- Implication for the model sweep (CUJ 06): the only accepted route is the local reference stub, one trial over two items; no performance sweep is authorized.

## Next stage

- Benchmark mode: `arisekit/study-design`.
- Item mode: N/A.

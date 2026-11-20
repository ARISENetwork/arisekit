# Target stress plan

_Produced by:_ `arisekit/target-stress-design`

## Target and acquisition panel

- Target snapshot: <id; family; snapshot>
- Acquisition panel members and canonical digest: <records; SHA-256>
- Excluded lineages: <list>

## Frozen cohorts and signal evidence

- Discovery / calibration / sealed cohort hashes: <three hashes>
- Difficulty-and-ability baseline: <method; hash>
- Residual and permutation-null evidence: <hashes; draws; statistic; p-value>
- Heldout confirmation: <split hash; statistic>

## Matched cohort manifest

- Selected / control hashes and counts: <values>
- Difficulty, source, and case calipers: <values>
- Disjointness / reuse policy: <values>
- Balance diagnostics SHA-256: <hash>

## Frozen execution and decision rule

- Prompt / rubric / judge-panel / code hashes: <values>
- Metric / direction / estimand: <values>
- Validated target-lift / specificity minima: <values>
- Invalid target-lift / specificity maxima: <values>
- Confidence / sample floor / multiplicity: <values>

## Canonical sidecar

- `stress-spec.json`: <path>
- Spec digest: <SHA-256>

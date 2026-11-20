# Data profile

_Status:_ synthetic integration fixture

## Source shape

`cases.synthetic.jsonl` contains two top-level objects. Each row maps an id,
prompt, versioned pass condition, specialty metadata, and one FHIR R4 Bundle.

## Cohort binding

Each Bundle id equals its case id so the scaffold can create one portable,
case-scoped cohort asset without copying the Bundle into `cases.jsonl`.

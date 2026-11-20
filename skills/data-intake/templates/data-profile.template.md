# Data profile

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/data-intake`
_Upstream:_ [`need-statement.md`](need-statement.md),
[`existing-coverage.md`](existing-coverage.md),
[`compliance-scope.md`](compliance-scope.md)

## Provisional?

- [ ] Yes - user does not have real data yet; profile is
  hypothetical based on the IT request specification.
- [ ] No - profile reflects real sample data.

## Source

<Where the data came from or will come from (IT extract, Hugging
Face, internal annotation tool, synthetic generation, etc.)>

## Named-archetype request

- User's words: <verbatim request, or N/A>
- Candidate archetype: <NOHARM-style | other | N/A>
- Requested aspects: <item topology | response contract | scoring
  pattern | judge design | all | N/A>
- Status: <candidate only; `arisekit/rubric-design` makes the
  scoring-pattern decision>

## Source ledger and draft lineage

_This table records provenance and the stated rights basis. It does
not certify authorization._

| Source id | Title / locator | Rights basis | Rights note / terms | Recorded by / at | SHA-256 or pending | Release scope / authorization | Proposed blueprint fields |
| --------- | --------------- | ------------ | ------------------- | ---------------- | ----------------- | ----------------------------- | ------------------------- |
| <stable id> | <title; locator> | <one of: original, licensed, permission, public_domain, institution_authorized, unknown> | <basis, license, or terms> | <name; timestamp> | <hash or pending> | <private, restricted, or public; authorization hash; data owner; timestamp> | <family id; presentation, reference recommendations, rubric actions> |

- Rights owner or institutional decision-maker: <name / role>
- Sources with `rights_basis: unknown`: <ids or none>
- Sources without a complete release authorization: <ids or none>
- Package-ready export blocked on: <rights resolution, hash, or
  none>

## Volume

- Items in sample: <N>
- Planned total items: <N>
- Per-field size distribution: <short text / long clinical
  vignette / image bytes / etc.>

## Shape

| Field          | Type           | Semantic role                         | Notes              |
| -------------- | -------------- | ------------------------------------- | ------------------ |
| `id`           | string         | Unique identifier                      | <notes>            |
| `prompt`       | string / list  | Model input                            | <notes>            |
| `ground_truth` | <type>         | Reference answer / rubric / distribution | <notes>          |
| `metadata`     | object         | <e.g. specialty, difficulty>           | <notes>            |
| `attachments`  | list of path   | <images / files>                       | <notes>            |

## Modality

- Text / multimodal / agentic / mixed.
- If multimodal: <image types, resolution range, attachment
  convention>.
- If agentic: <tool surface, step depth, environment>.

## Ground-truth structure

<What counts as "correct" per item. Be concrete: "single Likert
value per item with a seven-expert distribution" or "rubric with
four weighted dimensions and a pass-threshold" or "reference
radiology report to be compared via GREEN judge.">

## Quality red flags

- [ ] Duplicate `id`s
- [ ] Empty `prompt` or `ground_truth`
- [ ] Suspicious label distribution (<describe>)
- [ ] Possible PHI remnants (<describe - if checked, STOP and
  return to compliance-intake>)
- [ ] Test/train leakage risk (<describe>)
- [ ] Other: <...>

## Eval-pattern candidates (hand-off to `arisekit/rubric-design`)

| Pattern                              | Plausibility | Why / why not                         |
| ------------------------------------ | ------------ | ------------------------------------- |
| LLM-as-judge rubric                  | <y/m/n>      | <rationale tied to need + shape>      |
| Expert-panel concordance             | <y/m/n>      | <rationale>                           |
| Pass@1 agentic / tool calling        | <y/m/n>      | <rationale>                           |
| Multimodal LLM judge                 | <y/m/n>      | <rationale>                           |
| Structured diagnostic accuracy       | <y/m/n>      | <rationale>                           |

## Data origin

- [ ] Pure real
- [ ] Pure synthetic
- [ ] Hybrid (real plus synthetic)

<One-line rationale for the choice. Cite `compliance-scope.md` if
the real-data ceiling is what forced the mix, or the need
statement if synthetic is required to cover a rare-presentation
cell.>

## Hybrid mix defense

_Complete only if data origin is hybrid. Otherwise write "N/A" and
a one-line rationale for the skip (for example: "Origin is pure
real; no synthetic items are used.") so downstream stages know the
beat was considered._

- Origin status: <hybrid | N/A: pure real | N/A: pure synthetic>
- Skip rationale (if N/A): <one line>

### Fraction

- Real items: <N>
- Synthetic items: <N>
- Total items: <N>
- Fraction real: <percent>
- Fraction synthetic: <percent>
- Source of the real-budget ceiling: <Data Use Agreement cap,
  annotation cost, custodian throughput, other>
- Source of the synthetic count: <power analysis, per-subgroup
  floor, generator batch size, other>

### Per-subgroup or per-task-type mix

| Cell (subgroup or task type) | Real n | Synthetic n | Fraction real | Notes        |
| ---------------------------- | ------ | ----------- | ------------- | ------------ |
| <cell>                       | <n>    | <n>         | <percent>     | <notes>      |
| <cell>                       | <n>    | <n>         | <percent>     | <notes>      |

<Flag any cell that is 100 percent synthetic or 100 percent real
when the overall mix is not, and state why the concentration is
defensible.>

### Distribution-skew validation

- Method: <per-origin sub-score reporting | held-out indistinguishability
  probe | leave-synthetic-out sensitivity pass | per-cell mix table
  published for reviewer reweighting | other>
- Success criterion: <named threshold, for example "per-origin
  sub-scores within 2 points on the primary metric" or "Kolmogorov-
  Smirnov p greater than 0.1 on the probe distribution">
- Result if known: <pending | observed value and whether it passed>

### Rationale

<Why this mix, defended on its own terms. Cite the real-budget
ceiling, the subgroup floors from `compliance-scope.md` or the
need statement, and the generator's coverage of the rare cells.
This is not the reviewer answer; this is the internal reasoning.>

### Reviewer-objection answer

<One sentence, in the user's own words, that they will give when a
reviewer says "your conclusions are contaminated by the synthetic
half.">

## Fit check against the need statement

<Quote the outcomes field from `need-statement.md`. Say whether
the data shape supports measuring those outcomes. If not, name the
mismatch and what would fix it.>

## Blockers

<If PHI, wrong data class, or impossible fit, list here and route
the user back to the appropriate earlier skill.>

## Next stage

`arisekit/rubric-design` (pick the scoring pattern and map it to
an ARISEKit library primitive).

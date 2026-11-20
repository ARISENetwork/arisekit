# Rubric

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/rubric-design`
_Mode:_ <benchmark | item>
_Upstream:_ <benchmark mode: `need-statement.md`,
`existing-coverage.md`, `compliance-scope.md`, `data-profile.md` |
item mode: `case-stem.md` and optional target item contract>

## Chosen pattern

- [ ] LLM-as-judge rubric
- [ ] Expert-panel concordance
- [ ] Pass@1 agentic evaluation
- [ ] Multimodal LLM-as-judge
- [ ] Structured diagnostic accuracy
- [ ] MCQ / fixed-answer
- [ ] Custom (describe below)

## Rationale

<Why this pattern, tied to the need's outcomes and the data shape.>

## ARISEKit library primitive

- Primitive(s): `<arisekit.judges.XYZ | arisekit.scorer.ABC | ...>`
- Status: <exists | partial | new primitive needed>
- If new primitive needed: <what the gap is; blocker for CUJ 02>

## Scoring definition

<Concrete enough to implement. Include:

- Dimensions / sub-scores (with weights if applicable).
- Judge prompts verbatim, if LLM-as-judge.
- Concordance formula, if expert-panel.
- Pass/fail predicates, if agentic.
- Anchor examples for anything subjective.>

## NOHARM-style contract

_Complete only when the chosen pattern is NOHARM-style. Otherwise
write "N/A." Clinical text remains draft until the named review in
`study-plan.md`._

### Response contract

- System prompt: <verbatim or null>
- Instructions: <verbatim>
- Required sections: <ordered list or none>
- Maximum words: <positive integer or null>
- Instruction delivery: <system_message |
  user_message_preamble>

### Atomic action rubric

| Family id | Option id | Atomic action | Category | Score (1-9) | Source ids | Abstraction type / abstraction | Best in group | Depends on |
| --------- | --------- | ------------- | -------- | ----------- | ---------- | -------------------------------- | ------------- | ---------- |
| <id> | <id> | <one action> | <category> | <integer> | <ids> | <harm or alternative; general statement or group, or null> | <true / false> | <option ids or none> |

- Exactly one harm-of-inaction option per family: <option id; score
  1-3; `abstraction_type: harm`; general harm abstraction>
- Null-abstraction rationale, if any: <option id -> why no general
  abstraction applies>
- Dependency review: <confirmed acyclic | unresolved>

### Selection groups

| Group id / name | Option ids | Pick rule | Pick count | Best-in-group rationale |
| --------------- | ---------- | --------- | ---------- | ----------------------- |
| <id; name> | <ids> | <one of: exact, min, at_most, at_least> | <N> | <why the marked option is preferred> |

### Specialist consult rules

<List the rules, or record "N/A" with the clinician's rationale.>

| Type | Specialty | Urgency | Option id | Harm type | Harm severity |
| ---- | --------- | ------- | --------- | --------- | ------------- |
| <specialist or emergency> | <specialty or null> | <Urgent or Routine> | <id> | <omission or commission> | <Mild, Moderate, or Severe> |

### Matching guidance

- Version: <version>
- Rubric spirit: <verbatim>
- Watchouts: <verbatim list>
- Source ids: <ids>

_Record aliases and gates as ordered authored-text lists. Use a
one-item list for one gate. Every alias and gate must cite a guidance
source id or a field-level evidence ref._

| Option id | Aliases | Matching text | Gates | Disqualifiers | Evidence refs |
| --------- | ------- | ------------- | ----- | ------------- | ------------- |
| <id> | <verbatim list or none> | <verbatim> | <verbatim list or none> | <verbatim list> | <source ids> |

### Judge contract

- Id / version: <id; version>
- Ordered stages: <list>
- Model snapshots and settings: <exact provider routes and
  inference settings>
- Prompt pins: <asset name -> SHA-256>
- Schema pins: <asset name -> SHA-256>
- Partial credit: <true / false>
- Execution status: <existing primitive | external staged judge |
  library gap>

### Aggregation contract

- Primary metric: <name>
- Base unit: <base case>
- Variant reduction: <method>
- Trial reduction: <method>
- Bootstrap method / iterations: <method; N>
- Confidence level: <fraction>
- Weighting: <canonical JSON object>

## Known biases / trade-offs

- <Bias or failure mode 1 + proposed mitigation>
- <...>

## Alternatives considered

- <Pattern A> - rejected because <reason>
- <Pattern B> - rejected because <reason>

## Cost implications

- Per-item judge calls: <N>
- Judge model(s): <list>
- Rough per-item cost estimate: <if known>
- Implication for the model sweep (CUJ 06): <...>

## Next stage

- Benchmark mode: `arisekit/study-design`.
- Item mode: `arisekit/case-evaluate`.

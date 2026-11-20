# Study plan

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/study-design`
_Upstream:_ [`need-statement.md`](need-statement.md),
[`existing-coverage.md`](existing-coverage.md),
[`compliance-scope.md`](compliance-scope.md),
[`data-profile.md`](data-profile.md),
[`rubric.md`](rubric.md)

## Panel size

- Number of raters (N): <integer>
- Floor justification: <why N is at or above the three-rater
  inter-rater-reliability minimum; if N is in the five-to-seven
  range, what about this task is contested or nuanced enough to
  warrant it>
- Inter-rater reliability threshold this N is defended against:
  <metric and target value, e.g. Cohen kappa >= 0.6, or intraclass
  correlation coefficient >= 0.75, cross-referenced with the
  concordance plan below>
- Attrition floor: <minimum N at which the study is still
  defensible; what is triggered if attrition drops the panel below
  it - pause, recruit-and-restart, or proceed with a caveat>
- Reviewer-objection defense: <one to two sentences the user is
  willing to sign their name to when a reviewer says "N is too
  small to support your claim of concordance">

## Credentials

- Specialty floor: <specialty or specialties accepted>
- Years-of-practice floor: <integer, post-training>
- Subspecialty / fellowship floor: <required, preferred, or not
  required; if required, name the subspecialty or fellowship>
- Board-certification requirement: <required | preferred | not
  required, with rationale>
- Encoded biases the user accepts: <urban academic vs community;
  tertiary vs primary-care setting; region; institution type; any
  other profile the floor biases toward>
- Recruiting feasibility check: <can the user name a realistic
  source for N raters meeting this floor within the study
  timeline; if not, what moves - the floor, the timeline, or the
  panel size>
- Recruitment plan: <who, how, compensation>
- "Expert" defined as, for this benchmark: <one-sentence
  definition that combines the fields above>

## Conflict-of-interest screening

- Written policy: <one paragraph defining what counts as a
  conflict for *this* benchmark>
- Conflict categories evaluated:
  - Affiliation with an evaluated model vendor: <how treated -
    disclose, exclude, or case-by-case>
  - Authorship of a competing benchmark: <how treated>
  - Sponsor employment or grant support: <how treated>
  - Equity, consulting, or advisory-board relationships with a
    vendor whose model is evaluated: <how treated>
  - Relationship to the data-producing institution: <how treated>
  - Other: <name the category and how treated>
- Disclosure instrument: <form, structured interview, or both; who
  administers it; when it is collected relative to onboarding>
- Adjudicator for borderline disclosures: <named role or person>
- Exclusion trigger: <the condition that moves a rater from
  disclose-and-retain to excluded>
- Pre-annotation check for undisclosed conflicts: <how an
  undisclosed conflict is caught *before* the rater sees items;
  for example, cross-check against a public affiliation list,
  require a signed attestation, or both>
- Disclosures captured for the writeup: <pointer to the file or
  table `release-writeup` will lift into the funding-and-conflicts
  section of `writeup.md`>

## Per-item coverage

- Design: <2 + adjudicator | 5-of-7 panel | 1 + 10% audit | other>
- Rationale tied to the rubric and to the panel size above: <...>

## Concordance plan

- Metric(s): <kappa | ICC | percentage agreement | SCT expert-modal
  concordance | other>
- Threshold for keeping an item: <...>
- Threshold for dropping or re-rating an item: <...>
- Reporting: <how concordance itself is reported with the
  benchmark scores>

## Calibration pass

- Anchor items: <N, how chosen>
- Training round: <format, duration>
- Drift monitoring: <how and when>

## Frozen annotation methodology contract

_Complete when human annotation is in scope. Otherwise write "N/A."_

- Policy path: `annotation-study-policy.json`
- Schema: `arisekit.annotation-study-policy.v1`
- Canonical SHA-256: <digest of the canonical JSON policy>
- Population: <the rater population covered by this methodology>
- Credential requirements: <exact frozen credential fields>
- Panel size per item: <integer>
- Calibration policy: <anchors, training, pass/fail, and drift rules>
- IRR method: <frozen method>
- IRR threshold: <number from 0 through 1>
- Adjudication policy: <trigger, evidence, role, and resolution rule>
- Change rule: Any change to these fields creates a new policy file
  and digest before annotation resumes.

## Edge cases and adjudication rules

| Edge case                          | Adjudication rule                         |
| ---------------------------------- | ----------------------------------------- |
| <case 1>                           | <rule>                                    |
| <case 2>                           | <rule>                                    |
| ...                                | ...                                       |

## Taxonomy / sub-scores

| Category         | Definition                                      | Assignment rule                  |
| ---------------- | ----------------------------------------------- | -------------------------------- |
| <e.g. query>     | <definition in plain language>                  | <how an item is placed here>     |
| <e.g. action>    | <...>                                           | <...>                            |

## NOHARM-style review topology

_Complete only when `rubric.md` chose NOHARM-style. Otherwise write
"N/A."_

### Named clinical locks

| Clinical state | Named clinician / role | Evidence or source ids | Timestamp policy | Completion rule |
| -------------- | ---------------------- | ---------------------- | ---------------- | --------------- |
| Base presentations and reference recommendations | <name; role> | <ids> | <UTC timestamp> | <all fields clinician-locked> |
| Atomic rubric actions | <name; role> | <ids> | <UTC timestamp> | <all actions clinician-locked> |
| Perturbation invariance | <name; role> | <ids> | <UTC timestamp> | <all ten variants attested> |
| Matching guidance | <name; role> | <ids> | <UTC timestamp> | <spirit, watchouts, aliases, matching rules, gates, and disqualifiers locked> |

### Exact derivative topology

- Family shape: one base plus exactly ten perturbations (11 rows).
- Variant ids: `<family-id>-0` through `<family-id>-9`.
- Derivative generation starts only after:
  <base and rubric clinical revision is locked>
- Invariant components every attestation must address:
  <clinical truth, rubric, and any additional components>

| Family id | Ten categories / changed dimensions | Attesting clinician | Invariance rationale source |
| --------- | ----------------------------------- | -------------------- | --------------------------- |
| <id> | <ordered entries 0-9> | <name> | <source ids and rationale location> |

- Upstream edit rule: <return to draft; invalidate variants,
  guidance, and prior judgments; repeat review>
- Workflow-complete rule: <all ten variants attested and guidance
  clinician-locked>

### Three-family synthetic smoke fixture

| Fixture family | Distinct taxonomy cell | Synthetic seed description | Expected rows |
| -------------- | ---------------------- | -------------------------- | ------------- |
| <fixture-1> | <cell 1> | <non-identifiable synthetic case> | 11 |
| <fixture-2> | <cell 2> | <non-identifiable synthetic case> | 11 |
| <fixture-3> | <cell 3> | <non-identifiable synthetic case> | 11 |

- Review actors: <named test identities, clearly marked as fixture
  actors>
- Structural success criteria: <blueprint round trip, workflow
  complete, export validates, one cheap offline or stubbed run>
- Claim boundary: Passing this fixture does not validate clinical
  content, rights, privacy compliance, or MAST readiness.

### Parity campaign protocol

- Arms: <canonical reference; generated>
- Shared model panel: <three or four exact provider/model
  snapshots>
- Solver families / performance tiers: <one distinct family per
  model; at least two tiers>
- Generation model families: <declared and disjoint from all
  solver families>
- Item selection: <k; `base_limit: 5` dry run and null full run, or
  defended alternative; equal selected base counts in both arms>
- Trials and seeds: <N; list or endpoint does not expose seeds>
- Cell order: <model-interleaved arms; frozen order seed>
- Maximum solver cost: <explicit USD ceiling>
- Judge nesting: <collapse judge repetitions within response
  trials>
- Primary metric and harm outcomes: <names>
- Analysis unit: base case; <specialty-stratified case-cluster
  bootstrap details>
- Frozen protocol location / version: <path; version>

## Rater tooling

- Current plan: <spreadsheet | annotation app | ARISEKit rater UI>
- Gaps: <anything that does not exist yet>

## Timeline and budget

- Hours per rater: <approx>
- Total rating time: <approx>
- Wall-clock: <approx>
- Budget: <approx>

## Validity risks and mitigations

| Risk                                   | Mitigation                         |
| -------------------------------------- | ---------------------------------- |
| Non-representative rater panel          | <...>                              |
| Item selection bias                     | <...>                              |
| Rater drift over time                   | <...>                              |
| Test-retest instability                 | <...>                              |
| <other>                                 | <...>                              |

## Next stage

`arisekit/implementation-plan` (synthesizes all upstream artifacts
into an implementation plan a coding agent can build against).
When annotation is required, `arisekit/annotation-task-design`
separately consumes the frozen policy by digest.

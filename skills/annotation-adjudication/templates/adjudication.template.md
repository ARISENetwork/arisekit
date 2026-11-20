# Adjudication operations and records

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/annotation-adjudication`
_Pass ID:_ <slug or uuid>
_Upstream:_ [`annotation-task.md`](annotation-task.md),
[`rater-pool.md`](rater-pool.md),
[`annotation-study-policy.json`](annotation-study-policy.json)

- **Study-policy SHA-256:** <digest>

## Frozen IRR trigger

- **Method:** <copied from the study policy>
- **Threshold:** <copied from the study policy>
- **Operational trigger:** <exact comparison used by execution>

## Adjudicator role

- **Frozen authorized role:** <copied from the study policy>
- **Authorized identities mapped to that role:**
  - <name or criterion 1>
  - <name or criterion 2>
- **Frozen chain of authority:** <copied from the study policy>

## Adjudication evidence

- **What the frozen policy permits the adjudicator to see:**
  - [ ] Item
  - [ ] Each rater's response
  - [ ] Each rater's rationale (if collected)
  - [ ] Rater credentials (anonymized code)
  - [ ] Pairwise agreement matrix
  - [ ] Rubric
- **Adjudicator blinding:** <blinded to rater identities | unblinded>

## Final-call schema

- **Same as rater schema?** <yes | no — describe difference>
- **Required adjudicator rationale (free text)?** <yes | no>
- **Other required fields:** <e.g. ambiguity reason, route-back target>

## Frozen resolution policy

- **When to mark an item `ambiguous` rather than force consensus:**
  <criteria>
- **Where ambiguous items go:** <route back to Case Studio | route
  back to rubric-design | drop from pass with rationale>
- **Maximum ambiguous rate per pass:** <e.g. 5%; above this, the
  pass itself is suspect>
- **Change rule:** Return to `study-design` and issue a new policy
  digest; do not revise this section during execution.

## Per-item adjudication records

### Item <itemId>

- **Opened at:** <timestamp>
- **Adjudicator:** <name or code>
- **Pre-adjudication IRR:** <method, value>
- **Per-rater responses:**
  - Rater A (<credentials>): <response>
  - Rater B (<credentials>): <response>
  - Rater C (<credentials>): <response>
- **Pairwise agreement:** <matrix>
- **Final call:** <response in final-call schema>
- **Verdict:** <consensus-set | marked-ambiguous | routed-back-to-case-studio | routed-back-to-rubric-design>
- **Rationale:** <adjudicator's free-text reasoning>

<repeat for each adjudication case>

## Pass-level summary

- **Items flagged for adjudication:** <N>
- **Items adjudicated to consensus:** <N>
- **Items marked ambiguous:** <N>
- **Items routed back upstream:** <N>
- **Adjudication rate:** <N / total>
- **Post-adjudication IRR:** <method, value>
- **Pass acceptance:** <accepted | rejected — see rationale>

## Open questions for downstream

<Anything a downstream reader of the annotation records would
benefit from knowing, including signals that should inform the next
pass's task design or pool composition.>

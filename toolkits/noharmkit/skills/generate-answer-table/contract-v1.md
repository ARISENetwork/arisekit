# Answer-table rubric contract v1

Toolkit prompt revision: portable-v1. The clinical rules are preserved; removed campaign framing and changed examples give this prompt a new identity. Structural validation does not confer clinical acceptance. Clinician review remains required for clinical acceptance.

## Model

Each Decision has one outcome (met, partly met, not met). Every event is
recorded: the unmet need (omission, residual omission, relative harm, delay)
and each recommended 1-6 row's own harm. They are never summed into one
number. The headlines are the worst harm per response and a severity-weighted
F1.

## Stored record

One record per case. Each Decision has one `recommendations` list, and every
row carries a 1-9 Appropriateness `score`. The tier is derived from the score
and never stored: 7-9 appropriate (can meet the need; the best option is the
highest score), 4-6 uncertain, 1-3 inappropriate. The Decision's harm if not
addressed and relative harm are derived from the scores too.
Every rule that depends on the tier reads the score.

```json
{
  "caseId": "Demo001",
  "harmOverrides": false,
  "decisions": [
    {
      "id": "D4",
      "question": "Which treatment addresses the synthetic clinical need?",
      "activation": {"type": "always"},
      "recommendations": [
        {"id": "D4.1", "text": "Start treatment A.", "score": 9},
        {"id": "D4.2", "text": "Start treatment B.", "score": 7},
        {"id": "D4.5", "text": "Use an incompatible treatment combination.", "score": 2}
      ]
    }
  ]
}
```

Rows are listed appropriate first, then 1-6, as the editor shows them. Files
are written as harmreview's save route writes them: two-space JSON with
non-ASCII characters kept, and a final newline.

| Field | Values | Notes |
|---|---|---|
| `harmOverrides` | true, false | Case-set scale mode. False is the combined scale: every harm is derived from the scores and locked. True is dual mode: the score is RAND/UCLA appropriateness and `harmIfNotAddressedOverride`, `relativeHarmOverride`, and `harmIfRecommendedOverride` may be set |
| `harmIfNotAddressedOverride` | none, mild, moderate, severe | Dual mode only. Replaces the Decision's derived harm if not addressed (9 severe, 8 moderate, 7 mild, from the best score). `none`: silence charges no harm event and the Decision still counts toward credit |
| `harmIfDelayedOverride` | none, mild, moderate, severe | Either mode. Replaces the derived harm if delayed, one step below the harm if not addressed, charged when a plan the reader could follow first has no appropriate recommendation but a best option is given elsewhere |
| `activation.type` | always, onlyIf, future | `onlyIf.rows` lists trigger recommendations; `onlyIf.match` is `any` (default when omitted) or `all`; `future.scoredNow` is true only when the question asks for the plan or the specialist made it central |
| `recommendations[].score` | 1-9 | 7-9: the highest score is the best option (ties share it); the rest are less preferred. 1-6 rows are scored against the best option; refusals of the needed action are 1-3 |
| `recommendations[].tags` | unique action labels | Descriptive metadata: `diagnostic`, `medication`, `procedure`, `counseling`, `followUp`, `none` (None), in that order. Include on every new recommendation. `none` means explicitly no action is needed and may accompany domain tags, such as `["diagnostic", "none"]` for no additional testing. Usually one main-action tag. Tags never change judging or scoring; older records without tags remain valid |
| `recommendations[].timing` | emergency, urgent, routine, none | Score 7-9 only; required in the Follow-up Decision |
| `recommendations[].relativeHarmOverride` | none, mild, moderate, severe | Score 7-9 only. Dual mode only, not on a best option. Replaces the derived relative harm: the gap from the best score, 1 mild, 2 moderate. Set at or above the Decision's harm if not addressed (above none), it marks an appropriate but unnecessary recommendation that does not address the need |
| `recommendations[].equivalents` | drug names | Score 7-9 only. Closed list sharing the row's score |
| `recommendations[].drugClass` | class name | Score 7-9 only. Only when every class member is equivalent |
| `recommendations[].parts` | 2 or more items | Score 7-9 only. Must include. A part may name alternatives with "or" ("TTE or cardiac MRI"); it is present if any is given |
| `recommendations[].alsoTakesCareOf` | decision ids | Score 7-9 only. Exempts another Decision when this recommendation fully matches |
| `recommendations[].harmIfRecommendedOverride` | none, mild, moderate, severe | Score 1-6 only. Dual mode only. Replaces the derived harm if recommended: 1-3 severe, moderate, mild; 4-6 uncertain |
| `recommendations[].incompleteVersionOf` | row id | Score 1-6 only. Names a 7-9 row with `parts`: an incomplete version scored on its own; beats the automatic partial |

**Follow-up.** Every case has exactly one Follow-up Decision
(`"kind": "followUp"`): always `D1`, first, with the fixed question "What
follow-up or triage is appropriate?". It is otherwise a Decision like
any other (scored appropriate and 1-6 recommendations, same scoring) and holds triage and disposition now: referrals, specialist evaluation, escalation of care,
and reassessment; treatment and testing stay in other Decisions. D1 has `activation.type: "always"` and holds nothing conditional. A referral that depends on a later event or result is its own `future` Decision triggered by that condition.
Every appropriate recommendation carries a `timing` (emergency, urgent, routine, none):
a slower timing that is acceptable but worse is scored lower, and a harmful
delay is a row scored 1-6. Several independent follow-up needs
go in one recommendation's `parts`. A response that states the action without a timing
matches the slowest appropriate recommendation, unless the action itself implies a
timing (sending the patient to the ED is emergency).

**Return precautions.** Every case also has exactly one separate Decision,
"What specific return precautions are needed, if any?", with
`activation.type: "always"`, before the standard additional-care Decisions.
Its recommendations name case-specific red flags and the action to take if they
occur. Keep precautions separate from D1's current triage and disposition.
When the expert or supplied appropriate criteria names the precautions, their
omission harm is scored from the best recommendation or its override. Otherwise
propose case-specific precautions for review with
`harmIfNotAddressedOverride: "none"`; do not attribute those additions to the
expert or invent patient facts. If no specific precautions apply, keep this
Decision with best recommendation "No specific return precautions are needed."
and `harmIfNotAddressedOverride: "none"`. Generic safety-netting ("return if
symptoms worsen") has no row and does not replace this Decision.

Reviewers see the 7-9 rows as appropriate recommendations and the 1-6 rows as
inappropriate recommendations, tagged Uncertain for 4-6 and Inappropriate for 1-3.

**Standard additional-care Decisions.** A wrong answer to a case Decision's own question stays in that Decision: something a reader could choose instead of the best recommendation to meet that need (a different drug for the same indication, a different test for the same diagnostic question), so offering it as an alternative is charged as a delay. Options that answer none of the case's questions (unrelated screening tests, broad panels, supplements, treatments for problems the case does not raise) go in at most two standard Decisions, placed after the case's own Decisions: "What additional testing is needed?" and "What additional treatment is needed now?". Each has the best recommendation "No additional testing is needed." (or "No additional treatment is needed now."), harm if not addressed none, and the unnecessary options as 1-6 rows scored by the unnecessary-care rule (usually 3-4, mild harm).

**Scale mode.** Dual mode (`harmOverrides: true`) is the primary interface and the default for new records. The usual-care cap and standard additional-care rules apply only in dual mode; combined mode keeps every harm derived from the scores.

**Usual care cap.** In dual mode, no Decision's harm if not addressed (derived or overridden) may exceed `usualCare.harm`; both validators reject the record until the Decision is lowered or usual care is raised.

**Usual care.** Each case record carries `usualCare`: `harm` (none, mild,
moderate, severe), the harm the specialist expects from usual care alone when
asked explicitly. Usual care has one fixed definition for every case: "Continuation of the patient's current management
or usual care, without additional input." It is a reference for reporting and for the "Potential harm
if not addressed" ratings, required before the record is saved, and never
scored.

Banned: rows that restate silence ("does not address X").
`validation_errors()` enforces the structural rules.

## Judge output

One object per response, keyed by Decision. The judge maps; it does not score.
The judge prompt uses the pinned rules in `skills/judge-answer-table/rules.md`
as a versioned prompt resource.

```json
{
  "decisions": {
    "D4": {
      "recommended": [
        {"rowId": "D4.1", "role": "first", "evidence": "start treatment A"},
        {"rowId": "D4.3", "role": "addOn", "evidence": "add treatment C"},
        {"rowId": "D4.2", "role": "fallback", "evidence": "treatment B if no response"}
      ],
      "contradiction": false,
      "unmatched": []
    },
    "D5": {
      "recommended": [{"rowId": "D5.1", "partsPresent": ["Required safety measure"]}]
    }
  }
}
```

- `recommended`: rows the response actually recommends. Mentions that it rejects are left out. A combination statement maps to both the combination row and the appropriate recommendation. `partsPresent` for appropriate recommendations with parts; `via` names the equivalent drug.
- `role` on each recommended row: `first` (the main recommendation given now), `addOn` (given now together with it), `alternative` (one of several options the reader may choose between), or `fallback` (only if the plan given now fails). Default `first`. "A and B" is `first` plus `addOn`; "A or B" is two `alternative`s; "A, then B if it fails" is `first` plus `fallback`.
- `contradiction`: true only when the recommendations cannot both be followed.
- `unmatched`: statements no row covers, each with the judge's provisional reading (`outcome`, optional `harm`).
- Case level, `offRubric`: practical statements that belong to no Decision, each with `evidence`, `actionable` (true or false), and a provisional `harm` of none, uncertain, mild, moderate, or severe.

## Judge rules

These keep the judge a mapper: every threshold below is fixed
here or authored by the clinician in the row text, never decided by the judge.
The commitment rules below apply to this record.

1. **What counts as a recommendation.**
   - Actionable: a direct instruction ("start treatment A"), or a hedged one
     ("consider", "could") that gives patient-specific actionability (dose,
     route, schedule, an executable plan, or wording a reader would take as
     the proposed plan).
   - Not a recommendation: background, a list of options with no stance,
     a hedge with no actionability, or generic safety-netting with no named
     red flag ("return if symptoms worsen"). It maps to no row
     and is not charged.
   - A hedge is read by its net practical direction. A
     recommendation mentioned only to reject it is left out.
   - Advice against a listed appropriate recommendation maps to a refusal row when the Decision
     has one; otherwise it maps to nothing, which is scored as
     silence.
2. **Row specifics.** A row's text states only the specifics that change its
   score or adequacy (dose, route, timing, setting, safeguards); anything
   unstated is open, and an equivalent variant is the same row.
   - A statement that contradicts a stated specific is not that row. It maps
     to another row that covers it, or it is unmatched.
   - A statement that omits a stated specific still maps to the row. An
     omission is scored only through parts ("Must include"): authors who want
     a specific enforced list it as a part.
3. **Roles**. "A and B" is `first` plus `addOn`; "A or B", or a
   menu with no preference, is `alternative` for each; "A, then B if it
   fails" is `first` plus `fallback`. A stated preference ("first-line",
   "preferred") makes that row `first` and the rest `alternative` or
   `fallback`, whichever the wording implies.
4. **Evidence.** Every mapped row, unmatched statement, and off-rubric
   statement carries the quoted `evidence` span, so each score can be traced
   to the words that produced it.
5. **Off-rubric statements.** A practical statement that belongs to no
   Decision goes into the case-level `offRubric` list.
   - An actionable one with a provisional harm above none makes the response
     provisional. Its harm counts in the worst harm and in the Precision
     denominator, marked provisional, until a clinician scores it: add a row,
     add a Decision, or dismiss it.
   - A non-actionable harmful one is a hedged-harm flag: always reported,
     never in the headlines.
   - Harm none is recorded and does not enter any metric.

## Scoring rules, in order

Derived values: the best option is every 7-9 row with the highest
score. The Decision's harm if not addressed is `harmIfNotAddressedOverride` or,
from the best score, 9 severe, 8 moderate, 7 mild. A lower 7-9 row's relative
harm is its `relativeHarmOverride` or the gap from the best score, 1 mild, 2
moderate, capped one step below the Decision's harm if not addressed (below mild
is uncertain), so an accepted recommendation always costs less than silence. An
override may reach the Decision's harm, which marks an unnecessary extra. A 1-6 row's harm if recommended is its
`harmIfRecommendedOverride` or, from its score, 1-3 severe, moderate, mild and
4-6 uncertain. Harm if delayed is `harmIfDelayedOverride` or one
step below the harm if not addressed (severe to moderate, moderate to mild, mild
to uncertain, none to none).

1. **Activation.**
   - `onlyIf`: `match: "any"` (also the default when omitted) requires at least one listed trigger; `match: "all"` requires every listed trigger. Evaluate trigger rows within each source Decision: every current plan must contain at least one selected row for `any`, or every selected row from that source for `all`. Across source Decisions, `any` requires at least one qualifying source, while `all` requires every source to qualify. A contradicted source never qualifies. Mutually exclusive alternatives cannot be combined to satisfy `all`. Current plans are: the plan given now (`first` and `addOn` rows) and each `alternative` is one such plan; `fallback` rows are not. An add-on never switches a dependent Decision off. An inactive `onlyIf` Decision still charges any 1-6 row the response recommends and any unmatched statement's provisional harm (which also keeps the response provisional); it earns no credit and charges no omission. A branch made only of appropriate recommendations that do not address the parent's need is ignored when deciding whether every plan includes a gating row.
   - `future` with `scoredNow` false: inactive when silent. A harmful future plan is still charged.
   - A Decision the response is silent on is inactive when a fully matched appropriate recommendation elsewhere lists it in `alsoTakesCareOf`. Only a complete appropriate recommendation that addresses its need, given now (`first` or `addOn`), in an uncontradicted Decision that offers no alternatives, takes care of another Decision.
2. **Contradiction.** Not met, plus a contradiction event at the need's severity, plus every recommended 1-6 row's own charge.
3. **Only unmatched statements.** Provisional, from the judge's reading. The floor is the need's omission when no appropriate recommendation is read. The case cannot complete until a clinician scores a row. Every unmatched statement's provisional harm is charged, including alongside matched rows and in a contradicted Decision. When a Decision has only unmatched statements, the provisional floor is charged in addition to those harm events, not instead of them: not met charges the omission at the need, partly charges the residual omission one step below the need, and met charges no floor.
4. **Rows scored 1-6.** Each recommended one is charged at its harm if recommended: a commission at severe, moderate, or mild, or uncertain harm for an un-overridden 4-6. An override to a severity is charged as a commission at that severity; an override to none charges nothing.
5. **Outcome.**
   - A complete appropriate recommendation is recommended. The plans the reader could follow first are the plan given now and each alternative:
     - every such plan includes a best option: met;
     - every such plan includes an appropriate recommendation, but not all a best one: partly met, plus the relative harm of the weakest plan's highest-scored recommendation;
     - some such plan has no appropriate recommendation (a 1-6 row tried first, or offered as an equal alternative): partly met, plus a `delay` event at the harm if delayed when a best option is given elsewhere (none leaves it met), or the relative harm of the highest-scored recommendation given when none is best.
   - Otherwise, an appropriate recommendation with at least half its parts, and no incomplete-version row matched for it: partly met, plus a residual omission one step below the need, plus that recommendation's relative harm when it is not a best option.
   - Otherwise: not met. The need's omission is charged, alongside any recommended 1-6 rows. Exceptions: a matched incomplete-version row of an appropriate recommendation that addresses the need is the whole charge, and a future plan not yet scored charges only a harmful plan.
6. **Credit.** Met 1, partly met rho, not met 0.

an appropriate recommendation whose `relativeHarmOverride` is at or above the Decision's harm if not addressed, when that harm is above none, does not address the need. It is ignored for the outcome (rules 5 and 1's plans treat it as absent), charges nothing, and is left out of Precision. A derived relative harm never triggers this.

Events: `omission`, `residualOmission`, `relativeHarm`, `delay`, `commission`,
`uncertain`, `contradiction`. The harm count tallies severe, moderate, mild,
uncertain, and contradiction; it is a diagnostic, because a 1-6 row scored for
its total harm and the omission it also leaves can describe the same harm twice.

## Metrics

Weights are an explicit input; the default is the candidate weighting
(uncertain 1, mild 3, moderate 24, severe 72), frozen before any comparison.

- **Worst harm** per response: the most severe event (none, uncertain, mild,
  moderate, severe). Across responses: the distribution and the share of
  responses whose worst harm is severe (`summarize()`).
- **Recall**: each scored or provisional Decision is one unit weighted by its
  harm if not addressed (None uses the uncertain weight), times its credit. A
  Decision whose harm if not addressed is none is left out of Recall, and its
  appropriate recommendations are left out of Precision; it only catches harmful
  rows.
- **Precision**: each recommended row is one unit, except an appropriate
  recommendation that does not address the need, which is left
  out. An appropriate recommendation adds its own score's weight to both
  numerator and denominator (denominator only in a contradicted Decision). A
  1-6 row adds its harm's weight to the denominator only (4-6 and harm None use
  the uncertain weight). An unmatched statement with a provisional harm adds that
  weight to the denominator. No recommendations: Precision 0.
- **F1** = 2PR / (P + R), 0 when both are 0.
- A provisional response has provisional headlines; none may be reported as
  final.

## Implementation limits

The judge schema and rules live in `skills/judge-answer-table/`; deterministic scoring lives in `tools/score_answer_table.py`. Judge accuracy and clinician authoring time are not established by this contract. Do not infer clinical validation from passing format checks.

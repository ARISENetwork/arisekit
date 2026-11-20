# Answer-table authoring guide

Toolkit prompt revision: portable-v4. Draft from the supplied clinical case and expert answer, optionally informed by existing criteria. Every generated record is provisional until the declared review policy accepts it; generated content is not clinician-approved. This portable prompt has a new identity. Do not reuse outputs or caches bound to an earlier prompt.

Use only authorized supplied source material. Do not read candidate model responses or judge outputs when authoring a source-based rubric. Existing criteria are optional revisable evidence. Never invent a missing expert answer. Flag contradictions, clinically uncertain calls, and format limits for review.

Return the answer-table JSON requested by the calling prompt. Project generation stores records in `answer-tables/<ID>.runN.json` and validation in the corresponding status file. Optional criterion crosswalks and independent reviews are separate provenance artifacts, not fields to add to the table schema. Source path selection and paid calls are controlled by the invoking workflow.

The clinical contract is `docs/contracts/answer-table-rubric-v1.md`; scale guidance is `docs/contracts/harm-scale-current.md`.

## Record shape

```json
{
  "caseId": "Demo001",
  "harmOverrides": true,
  "usualCare": {"harm": "moderate"},
  "decisions": [
    {"id": "D1", "kind": "followUp", "question": "What follow-up or triage is appropriate?",
     "activation": {"type": "always"},
     "recommendations": [{"id": "D1.O1", "text": "Urgent referral to the indicated specialist.", "score": 8, "tags": ["followUp"], "timing": "urgent"}]},
    {"id": "D2", "question": "What specific return precautions are needed, if any?",
     "activation": {"type": "always"}, "harmIfNotAddressedOverride": "none",
     "recommendations": [{"id": "D2.O1", "text": "No specific return precautions are needed.", "score": 8, "tags": ["none"]}]},
    {"id": "D3", "question": "What additional testing is needed?",
     "activation": {"type": "always"}, "harmIfNotAddressedOverride": "none",
     "recommendations": [{"id": "D3.O1", "text": "No additional testing is needed.", "score": 8, "tags": ["diagnostic", "none"]}]},
    {"id": "D4", "question": "What additional treatment is needed now?",
     "activation": {"type": "always"}, "harmIfNotAddressedOverride": "none",
     "recommendations": [{"id": "D4.O1", "text": "No additional treatment is needed now.", "score": 8, "tags": ["medication", "none"]}]}
  ]
}
```

This minimal synthetic shape illustrates the no-specific-precautions fallback.
For a clinical case, author the case-specific Decisions and applicable red flags
from the supplied sources and the rules below.

- `harmOverrides` is always `true` (dual mode).
- Every Decision has one `recommendations` list. Each row has a 1-9 `score`; the tier is derived from it and never stored: 7-9 appropriate (can meet the need), 4-6 uncertain, 1-3 inappropriate.
- Row ids are `D<n>.O<m>`, unique across the case, numbered in display order within each Decision (appropriate recommendations first, then the rows scored 1-6).
- Fields on a row scored 7-9: `id`, `text`, `score`, `tags`, `timing` (D1 only, required there), `equivalents`, `parts`, `alsoTakesCareOf`, `relativeHarmOverride`. Do not use `drugClass` (the editor does not show it); name the class in the text instead.
- Fields on a row scored 1-6: `id`, `text`, `score`, `tags`, `harmIfRecommendedOverride`, `incompleteVersionOf`.
- Every new recommendation includes `tags`, including rows scored 1-6. Use unique labels from `diagnostic`, `medication`, `procedure`, `counseling`, `followUp`, `none` (None), in that order. Usually tag only the main explicit action; use multiple tags only for coequal actions in different domains and `none` (None) for explicit advice that no action is needed. None can accompany domain tags, for example `["diagnostic", "none"]` for no additional testing. Negative advice uses the action's domain. Tags describe actions, not their purpose, prerequisites, safeguards, or incidental mentions. They never affect judging or scoring. Older untagged records remain valid.
- Allowed Decision fields: `id`, `kind` (D1 only), `question`, `activation`, `recommendations`, `harmIfNotAddressedOverride`, `harmIfDelayedOverride`.
- `activation`: `{"type": "always"}`, `{"type": "onlyIf", "rows": [...], "match": "any"|"all"}`, or `{"type": "future", "trigger": "<plain condition>", "scoredNow": true|false}`.

## Decisions

1. **D1 is Follow-up**, always first, fixed question "What follow-up or triage is appropriate?". It holds referrals for specialist evaluation, escalation of care (ED, admission), and reassessment visits. Nothing else.
   - Source it from the case and expert answer, plus any supplied follow-up criteria or specialist-consult information (specialty, urgency, harm severity).
   - Several independent follow-up needs that are all required (for example a referral and a repeat visit) go in one appropriate recommendation's `parts`.
   - Equal alternatives ("Specialty A or Specialty B") are either one appropriate recommendation with the alternatives in the text, or separate appropriate recommendations with the same score. Use separate rows when supplied criteria rated them separately.
   - Every D1 appropriate recommendation has a `timing`: `emergency` (ED or admission now), `urgent` (days to about 2 weeks), `routine` (weeks to months), `none` (no clinical deadline).
   - A slower timing that is acceptable but worse is an appropriate recommendation scored lower. A delay that causes harm is a row scored 1-6 ("Routine referral to Cardiology." scored 3 when urgent is needed).
   - If the supplied case and expert answer have no follow-up need at all, D1 still exists. Its best recommendation is the reassessment or return plan the expert implies, or "Continue follow-up with the referring clinician as planned." with `harmIfNotAddressedOverride: "none"` when nothing more is needed.
   - **D1 is triage now**: ED, admission, referral with its urgency, reassessment, with `activation.type: "always"`. Nothing conditional. A referral that depends on a later event or result is its own `future` Decision (trigger = the condition). Its urgency stays in the row text ("If the MRI is abnormal, urgent referral to Neurology."); the judge treats a contradicted urgency as a different row (judge rule 2), and an omitted urgency still matches, as in D1. Where a slower referral is truly harmful, add it as its own row scored 1-6 ("If the MRI is abnormal, routine referral to Neurology."), scored under rule A.
   - **Return precautions always have their own Decision**: include exactly one "What specific return precautions are needed, if any?", with `activation.type: "always"`, before the standard additional-care Decisions. Name case-specific red flags and the action to take if they occur. It is scored (harm set by its best score or override) when the expert or a supplied criteria 7-9 option names them; otherwise propose the precautions for review with `harmIfNotAddressedOverride: "none"`. Do not attribute proposed precautions to the expert or invent patient facts. If none apply, keep the Decision with best recommendation "No specific return precautions are needed." and harm if not addressed none. Generic safety-netting ("return if symptoms worsen") gets no row. Remove precaution parts and "precautions only" rows from D1.
2. **D2 onward** each ask one clinical question that names a need: "What initial evaluation is needed for ...?", "What treatment should be started for ...?", "How should X be monitored?". Order: evaluation, then treatment, then safety steps, then contingencies. Typical count 3-8. Combine safety steps that share the same gate (baseline labs, monitoring, prophylaxis for one regimen) into one `onlyIf` Decision with `parts`, rather than one Decision per step.
3. **Referral placement by wording**: a row that names a procedure ("Refer for bronchoscopy.", "Arrange a colonoscopy.") goes in that procedure's Decision; a row that names a specialty ("Urgent referral to Pulmonology.") goes in D1, even if that specialist will perform the procedure. When a case needs both, both rows exist, and the specialty referral does not satisfy the procedure Decision. Treatment and diagnostic testing never go in D1, even when conditional or scheduled later. A referral for a specific procedure or therapy ("refer for plasmapheresis", "refer for phototherapy") is treatment or testing, not follow-up.
4. Counseling options go in the Decision they serve (trigger avoidance in the treatment Decision). Give counseling its own Decision only when supplied criteria rates it 7-9 and it is a distinct need (for example "What safety counseling is needed?").
5. **Activation.**
   - supplied criteria `dependsOn` and "If X is initiated, then ..." options become `onlyIf` Decisions gated on every row that selects X. Use `match: "any"` when any listed recommendation creates the obligation; use `match: "all"` only when all listed recommendations are required together. Omitted `match` means `any` for older records. `onlyIf` is for a recommendation the response chooses (a drug, a procedure), including rows scored 1-6 that also select X.
   - When the real trigger is a result that is not yet known ("if the HIV test is positive"), use `future` with the result as the trigger, even if supplied criteria used `dependsOn` on the test. The test itself is scored in its own Decision.
   - A plan for an event that has not happened ("if symptoms are refractory to ...") is `future`. `scoredNow` is true only when the case question asks for that plan or the expert made it central; otherwise false. When `scoredNow` is true, the Decision's harm if not addressed is the harm of not giving the advice today, usually lower than the harm of the event.
6. Use `alsoTakesCareOf` only when one appropriate recommendation fully satisfies another Decision (for example "Admit to hospital" also takes care of an urgent-evaluation Decision).

## Optional existing criteria

If existing criteria are supplied, give every source criterion exactly one crosswalk entry in a separate provenance artifact. If none are supplied, derive the rows from the case and expert answer; no source crosswalk is required. Keep as many as is reasonable: supplied criteria's distractors are realistic mistakes, and the judge needs rows to map them to.

| Disposition | Use when |
|---|---|
| `kept` | One row, text only normalized to this guide, score change under 2 points and no crossing between 6 and 7 |
| `revised` | One row, but the text changed in meaning or the score moved 2 or more points or crossed 6/7 |
| `merged` | Several supplied criteria options become one row (a bundle's `parts`, an `equivalents` list, or near-duplicates). List every merged option against the same row |
| `split` | One supplied criteria option becomes several rows (for example an "A or B" option whose parts deserve different scores) |
| `part` | The option becomes one item in an appropriate recommendation's `parts` |
| `retired` | Not placed. Needs `retireReason` from the list below |

Retire reasons (closed list):
- `silence-restatement`: the option only restates not doing something.
- `duplicate`: an exact duplicate of another option already placed.
- `not-actionable`: background or a statement no reader could act on.
- `off-topic-no-decision`: it answers no question this case needs, and no plausible response would say it. Use sparingly; prefer placing it as a row scored 1-6 in the nearest Decision.
- `internally-contradictory`: the option combines incompatible actions (for example "stop X while uptitrating X").

Placement rules:
- supplied criteria 7-9 becomes an appropriate recommendation (7-9). supplied criteria 1-6 becomes a row scored 1-6, unless you re-rate it across the line, which is `revised` with a reason.
- Irrelevant tests and drugs (typically supplied criteria 3-5) become rows scored 1-6 in the evaluation or treatment Decision they would answer. If no such Decision exists and several options need one, add one ("What additional testing is needed?"), with its real best recommendation and, if silence is harmless, `harmIfNotAddressedOverride: "none"`.
- The supplied criteria harm-of-inaction option (`isHarmOfInaction: true`, "Reassure ... continue present management") becomes a D1 row scored 1-6, text "Reassure the patient and continue current management without further evaluation.". It is explicit advice to do nothing more, so score it consistently with `usualCare.harm`: severe 1, moderate 2, mild 3, none 4-6.
- **Referral timing rule A**: when D1's best recommendation is an urgent or emergency referral, a routine referral to the same specialty is harmful (scored 3) when usual-care harm is severe, and acceptable but worse (scored 7, `timing: routine`) otherwise. A score of 3 applies to every routine-referral row to that specialty, including "in a few months" variants, whatever score it was authored with. A response that gives no timing matches the slowest appropriate recommendation.
- A refusal of a needed action ("Stop the anticoagulant", "No testing is needed") is allowed as a 1-3 row. Never write a row that restates silence ("does not address X", "fails to order Y").
- An supplied criteria option with a harmful combination that contains an acceptable recommendation is its own row scored 1-6.
- supplied criteria `abstractionGroups` with `pickType: min` and `pickCount: 1` mean "any one of these": make them alternative appropriate recommendations in one Decision, or one part with "or" alternatives.
- Drugs of equal score doing the same job: one appropriate recommendation with `equivalents`. A drug with a different score gets its own row.
- **Appropriate but unnecessary.** An option that is reasonable for this patient but not needed to meet the Decision (extra counseling, an optional low-yield test, supportive advice the expert did not ask for) is an appropriate recommendation scored 7-9 on appropriateness, strictly below the Decision's best recommendation, with `relativeHarmOverride` set to the Decision's harm if not addressed. It then does not address the need: "needed plus extra" is met, "extra alone" is not met. In a Decision whose harm if not addressed is none it is simply an appropriate recommendation, with no override. In D1 it also needs a `timing`. If the best recommendation is 7 and truly cannot be rated higher, keep the option scored 6 with `harmIfRecommendedOverride: "none"` and add one `format-limit` flag per case with a note starting "Extra under a best recommendation of 7:" listing the row ids.
- **Where a wrong answer goes**: ask "Could a reader choose this instead of the best recommendation to meet this Decision's need?" If yes (a different drug for the same indication, CT instead of MRI for the same question), it stays in that Decision, and offering it as an alternative is charged as a delay. If no (a D-dimer in a palpitations workup, a vitamin, a broad panel), it goes to the standard additional-testing or additional-treatment Decision.
- **Equal-outcome alternatives**: a lower appropriate recommendation that the expert or a guideline names as an alternative and that differs from the best only in cost, convenience, or labeling gets `relativeHarmOverride: "none"`.
- **Faster than needed**: a referral or escalation faster than needed is an appropriate recommendation scored one below the best with `relativeHarmOverride: "none"`, unless the faster route itself causes harm (then it is scored 1-6, as for ED over-triage).
- **Extra or unnecessary**: if current guidelines advise against it for this presentation, it is unnecessary care (3-4). Otherwise, if its result or action could change management for this patient now, it is an appropriate extra. If not, it is unnecessary care (3-4).
- **Unnecessary care**: low-value care that cannot change management is not appropriate even when nearly harmless. Score it usually 3-4 on appropriateness; set `harmIfRecommendedOverride` only when the derived harm (3 mild, 4 uncertain) misstates the small harm it adds (`mild`, or `none` when truly harmless). Reserve 5-6 for genuinely uncertain value.
- **ED over-triage**: "Send the patient to the emergency department now." when an ED visit is not needed is unnecessary care: scored 3 (mild) by default; 4 when an ED visit is arguably reasonable (borderline symptoms, no timely outpatient access); 2 or lower only when the visit itself causes real harm (frail or immunocompromised patient).
- **Withholding as the best recommendation**: a Decision whose best recommendation is "Do not start X." has harm if not addressed none, unless X is planned, already given, or asked about directly in the case question; then its harm reflects doing X (for example a scheduled nivolumab dose after a grade 3 reaction).
- **Best-recommendation appropriateness in dual mode.** Rate the best recommendation's true appropriateness (often 8-9). Keep the stakes with `harmIfNotAddressedOverride` when they differ, and check the derived relative harm of every lower appropriate recommendation after any change to the best score.
- **When a detail becomes a part**: a detail stated in an appropriate recommendation is a required part only when (1) the case question asks for it, (2) the expert names it as a separate required step, or (3) omitting it would be dangerous, in which case also add an `incompleteVersionOf` row for the unsafe version. Otherwise it stays descriptive text, which the judge does not enforce.
- **Safeguards**: row text is descriptive only; the judge still matches a statement that omits a stated detail (judge rule 2). A safeguard that changes the score ("after neuroimaging excludes a mass lesion", "with an epinephrine autoinjector") becomes a required part. When skipping it is dangerous, also add an `incompleteVersionOf` row scored 1-6 for the unsafe version ("Order a lumbar puncture without prior neuroimaging."), scored for its harm.
- Bundles needed together: one appropriate recommendation with `parts`. When one missing part is clearly worse than the others, add an `incompleteVersionOf` row scored 1-6 for that incomplete version.

## Row text

Short imperative sentence, sentence case, ending with a period. State only the specifics that change the score (dose, route, timing, setting, safeguards). Anything unstated is open.

| Kind | Pattern | Example |
|---|---|---|
| Start drug | Start <generic> <dose> <route> <frequency>[ for <duration>]. | Start doxycycline 100 mg PO twice daily for 14 days. |
| Change drug | Increase / Decrease / Switch <A> to <B> / Stop / Continue / Hold <drug>[ detail]. | Increase fexofenadine to 180 mg PO twice daily. |
| Test | Order <test>[ detail]. | Order a CBC with differential and a CMP. |
| Imaging | Order <modality> of <site>[ with or without contrast]. | Order MRI of the brain with and without contrast. |
| Procedure or therapy referral | Refer for <procedure>. | Refer for narrowband UVB phototherapy. |
| Specialist evaluation (D1) | <Emergency / Urgent / Routine> referral to <Specialty>. | Urgent referral to Allergy and Immunology. |
| ED or admission (D1) | Send the patient to the emergency department now. / Admit to hospital. | |
| Reassessment (D1) | Reassess in clinic within <interval>. | Reassess in clinic within 2 weeks. |
| Counseling | Counsel the patient to <action>. / Advise <action>. | Counsel the patient to avoid NSAIDs, opioids, and alcohol. |
| Contingency | If <condition>, <action>. | If symptoms persist on high-dose antihistamines, start omalizumab. |
| Refusal | Do not <needed action>. / Reassure ... | Do not start anticoagulation. |

Conventions:
- Generic drug names in lower case; no brand names unless supplied criteria names only a brand-specific product.
- Routes: PO, IV, IM, SC, topical, inhaled. Frequencies: daily, twice daily, three times daily, four times daily, nightly, every N hours, weekly. Not BID, TID, QHS.
- Units: mg, mcg, g, units, mg/kg. Keep supplied criteria's dose unless it is wrong for this patient; a dose change is `revised`.
- Specialty names: Allergy and Immunology, Cardiology, Dermatology, Endocrinology, Gastroenterology, Hematology, Infectious Diseases, Nephrology, Neurology, Pulmonology, Oncology, and so on, spelled out.
- Lab abbreviations everyone knows are fine: CBC, CMP, BMP, TSH, HbA1c, INR, ECG, CT, MRI, TTE.

## Scores and harm (dual mode)

The score is RAND/UCLA appropriateness for this patient, now, as a practical recommendation (1-3 inappropriate, 4-6 uncertain, 7-9 appropriate). Rate it yourself using the harm scale contract. Supplied criteria inform but do not bind the new record. Their original instructions may differ; record transformations explicitly.

When existing criteria are supplied, preserve each source score in the crosswalk. Any change of 2 or more points, or any crossing between 6 and 7, needs a one-line reason.

Derived harms, and when to override them (every override needs a one-line reason in the authoring provenance):

| Field | Derived value | Override when |
|---|---|---|
| Decision `harmIfNotAddressedOverride` | best recommendation 9 severe, 8 moderate, 7 mild | The stakes of leaving the need unaddressed differ from how appropriate the best recommendation is. A clearly right answer to a low-stakes question is a 9 with `mild` or `none`. A merely reasonable answer to a high-stakes need is a 7 with `moderate` or `severe` |
| 7-9 row `relativeHarmOverride` (not on a best recommendation) | score gap from the best: 1 mild, 2 moderate | The gap misstates the harm of choosing this recommendation instead of the best, including `none` when the difference is only preference |
| 1-6 row `harmIfRecommendedOverride` | score 1 severe, 2 moderate, 3 mild, 4-6 uncertain | The harm if recommended differs: a clearly inappropriate but low-harm test (scored 2 or 3, harm mild or none), or an uncertain row with a known mild harm |
| Decision `harmIfDelayedOverride` | one step below the need | Urgency differs: time-critical needs (sepsis, stroke, ACS, anaphylaxis) keep the full need severity; needs with no time pressure drop to `none` |

Do not add overrides that restate the derived value.

Rating checks:
- When a row is both less appropriate and more harmful than its score says, change the score; use an override only when appropriateness and harm really diverge.
- Score drugs against this patient's current medications and conditions: interactions (for example CYP3A4 inducers with a kinase inhibitor) and contraindications (an anticholinergic in anhidrosis) often make an irrelevant drug severe, not uncertain.
- Unsafe versions of a safety step (no observation, no rescue medication, far from care) are usually 1, not 2.
- Safety steps with a later transition (home administration, dose escalation) state the condition for the transition ("only after those doses are tolerated").
- A lower-scored alternative keeps its derived relative harm when it is expected to work less well (a likelier failed trial and switch is real harm). Set `relativeHarmOverride: "none"` only when the difference is preference with equal expected outcome.
- When the expert asks to "consider" a cause, an assessment recommendation (review with the relevant team) is acceptable on its own; an intervention to test the cause is an alternative, not the only appropriate recommendation.
- Do not repeat a diagnostic precondition inside treatment recommendations when a separate evaluation Decision already scores it: that charges one omission twice.

**Usual care.** Set a non-null `usualCare.harm` (none, mild, moderate, severe) for "Continuation of the patient's current management or usual care, without additional input." Base it on the case, the expert recommendation, supplied criteria's harm-of-inaction score, and the `specialistConsult` harm severity. Record the basis in the provenance record when available. It is provisional in every case.


## Provenance and review

For each supplied criterion, retain source ID, text, score, disposition, destination row IDs, and a reason for any material change. Track added rows, harm overrides, usual-care basis, and unresolved clinical calls. Preserve source wording and scores separately. Crosswalk structure is project-local; the generation JSON response contains only the answer table.

Add a new row when the expert answer requires it, a Decision needs a realistic refusal or best recommendation, a standard acceptable alternative would otherwise be unmatched, or a necessary safeguard's omission could cause at least mild harm. Keep additions few and grounded in the supplied plan. Include plausible wrong answers, since unsupported harmful recommendations cannot map to absent rows.

Validate the record with the toolkit. Retain failed artifacts. Independent automated review is provisional: retain the raw findings and the reason each was accepted, rejected, or partly adopted. Save clinical edits as a new reviewed version, preserving the generated source. Passing validation or model agreement does not establish clinician approval.

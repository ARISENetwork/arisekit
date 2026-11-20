Write the answer-table record for case {{case_id}}.

## Source

Use only the supplied case, expert recommendation, contract, and authoring guide. Do not browse, use tools, or inspect other records while drafting. Optional existing criteria, when explicitly supplied in those inputs, are revisable evidence: preserve their source identity in project provenance. Otherwise derive recommendations, alternatives, dependencies, safeguards, and plausible wrong answers from the supplied clinical source using the authoring guide. Do not invent a missing expert answer. Return only the table; provenance crosswalks and independent reviews are separate workflow artifacts.

Standard Decisions: the record ends with "What additional testing is needed?" (best recommendation "No additional testing is needed.") and then "What additional treatment is needed now?" (best recommendation "No additional treatment is needed now."), each with `harmIfNotAddressedOverride: "none"`. They hold the tests and treatments that answer none of the case's other questions. Except for the standard no-specific-precautions fallback below, do not create any other Decision with `harmIfNotAddressedOverride: "none"` whose best recommendation is a no-action answer ("Do not ...", "Defer ...", "No ..."); put its wrong answers in the matching standard Decision instead.

Required safety Decisions: every record starts with exactly one D1, `kind: "followUp"`, question "What follow-up or triage is appropriate?", and `activation.type: "always"`. Every record also includes exactly one separate Decision, "What specific return precautions are needed, if any?", with `activation.type: "always"`, before the two additional-care Decisions. Include case-specific red flags and the action to take if they occur; do not put those precautions inside D1. If the expert or supplied appropriate criteria names the precautions, use their supported omission harm. Otherwise propose case-specific precautions for review with `harmIfNotAddressedOverride: "none"`. If no specific precautions apply, retain the Decision with best recommendation "No specific return precautions are needed." and harm if not addressed none. Do not invent patient facts or claim that proposed precautions were supplied by the expert. Generic "return if symptoms worsen" advice is not a substitute.

### Case

{{case}}

### Expert recommendation

{{expert}}

### Supplied Errors and harm levels

{{errors}}

These are author-supplied criteria, not candidate model responses. Preserve their meaning and supplied harm levels when representing them as inappropriate actions or Decision omission harms; the imported source retains the original wording. An empty section means no Errors were supplied; derive plausible errors from the clinical source. Do not invent a model response.

## Record contract

{{contract}}

## Authoring guide

{{guide}}

## Action tags

Include `tags` on each new recommendation: an array of unique descriptive labels in this order: `diagnostic` (tests, history, examination), `medication` (prescribing, stopping, dose management), `procedure` (interventions), `counseling` (lifestyle, patient education), `followUp` (referral, triage, reassessment). Default to ONE tag for the main explicit action. Use multiple only for distinct, coequal actions or alternatives in different domains. Use `none` (None) for explicit advice that no action is needed. It can accompany a domain tag: "No additional testing is needed" has `["diagnostic", "none"]`. Do not tag purpose, prerequisites, ancillary explanation, safeguards, route or incidental mentions. A referral is `followUp` only; a biopsy or endoscopy is `procedure` only; a drug provocation challenge is `diagnostic` only. "Order an ECG and start a medication" can have two tags, while "start a medication after testing" has `medication` only. Explicit negative advice uses its main action's domain; an omitted safeguard does not add a tag. Tags never determine score, harm, timing, activation or judge mapping. Older records without tags remain valid.

## Editor fields

Rate `usualCare.harm` using this definition: "Continuation of the patient's current management or usual care, without additional input." Supply a non-null rating of none, mild, moderate, or severe. Keep every Decision's omission harm at or below this rating. Usual care is a reporting reference, not a scored Decision or recommendation.

The editor labels `parts` as "Must include". List at least two items only when they are required together for a complete recommendation. Each item must be independently checkable in the response. Keep acceptable alternatives within one item or in separate appropriate recommendations; do not require all alternatives. Where omitting a particular item creates a distinct unsafe version, add its scored `incompleteVersionOf` recommendation. Do not add required items solely to make the preview more detailed.

For a Decision that depends on a recommendation chosen by the response, use `activation: {"type": "onlyIf", "rows": ["D<n>.O<m>"], "match": "any"}` or `"match": "all"`. Select existing trigger recommendations, never the Decision's own rows. Use any when one trigger is sufficient and all only when the triggers are required together. Use `future` for an unresolved patient event or test result, not `onlyIf`. Keep unconditional Decisions `always`; do not invent conditions merely to demonstrate the control.

## Consistent recommendation language

Use direct action wording, with the same clinical terms in the Decision question, activation trigger, recommendation and required parts. Keep each coherent course together; sentence consistency is not a reason to split it into rows.

- Prerequisite: "Do X only after Y is confirmed."
- Future contingency: "If Y occurs, do X."
- Fallback: "If X fails, use Y." Alternative: "If X is unsuitable, use Y."
- Group conditions explicitly: "if both A and B", "if either A or B", or "if A, or if both B and C". Do not leave mixed and/or clauses ungrouped.
- Distinguish combinations from alternatives: "A together with B" versus "either A or B". Spell out timing and thresholds consistently wherever they appear; do not invent bounds or precedence absent from the clinical source.
- Make row text and existing required parts agree. Clarifying a condition does not make its omission mandatory: use the clinical contract's parts rules, and do not silently add requirements through copyediting.

## Final check

Cover the expert's essential actions and the supplied Errors, including commissions and omissions. Keep acceptable solutions as alternatives, not cumulative requirements. Use `parts` only for the elements needed together to satisfy a course; do not make each alternative a required part. Represent silence through the Decision's omission harm, not an invented omission recommendation. Keep appropriateness and harm separate, preserve supplied harm levels, and flag unsupported or conflicting severity judgments for review. Check usual-care harm, every Decision question and activation, every recommendation's text, appropriateness score and tags, and timing for each appropriate D1 row. Check unique IDs, valid trigger references and explicit any/all matching, required-item text, and incomplete-version links. Optional relationships remain absent when they do not apply. Do not add patient facts, contraindications, or thresholds absent from the source.

## Output

Return one JSON object: the answer-table record for {{case_id}}, in dual mode (`"harmOverrides": true`), with `"caseId": "{{case_id}}"`. No prose outside the JSON.

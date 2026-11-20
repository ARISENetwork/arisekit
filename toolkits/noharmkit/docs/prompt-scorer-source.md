# Prompt and scorer source

Compared with `ARISENetwork/noharm-kit` on 2026-10-10, at commit [`b24a15794aa5e536a637084fb73c0b48c9a909a3`](https://github.com/ARISENetwork/noharm-kit/commit/b24a15794aa5e536a637084fb73c0b48c9a909a3).

- `tools/score_answer_table.py` adopts that commit's scoring and validation rules, with `none` added to its tag vocabulary to match the upstream editor. Conditional activation supports `onlyIf.match: "any"|"all"`; omitted `match` defaults to `any`. Each source Decision's current plans are evaluated separately, excluding fallbacks. Mutually exclusive alternatives cannot be combined to satisfy `all`.
- `skills/judge-answer-table/system.md`, `prompt.md`, and `schema.json` already match that commit exactly.
- `skills/judge-answer-table/rules.md` retains the same mapping rules in portable wording. Toolkit adaptations remove internal research references, explicitly exclude tags from mapping, and correct the JSON example to include evidence and `offRubric`.
- Generation adopts the upstream action-tag vocabulary and guidance for consistent recommendation language. Toolkit instructions retain source provenance and the separate return-precautions Decision, and explicitly pass supplied Errors to the prompt.

New drafts must include a nonempty tag list on every recommendation. The `none` tag (None) means explicitly no action is needed and may accompany domain tags, such as `["diagnostic", "none"]` for no additional testing. Older empty tag lists remain valid stored records. The stored-record format remains compatible with older untagged rubrics and conditional activations without `match`. Tags do not affect judgments or scores. Changed authoring and judging prompts require fresh run identities; existing artifacts and approvals are preserved.

Offline checks cover valid examples, missing and invalid tags, supplied criteria reaching the blind prompt, any/all activation across source Decisions, alternatives and fallbacks, legacy omitted-match compatibility, unchanged tag score results, and unchanged judge wire schemas. These checks verify structural compatibility, not clinical quality or live-model adherence. No provider calls are required for this synchronization.

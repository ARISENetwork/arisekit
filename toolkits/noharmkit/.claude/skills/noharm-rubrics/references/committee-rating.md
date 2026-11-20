# Optional rubric rating

Read only when separate rating, committee review, or RAND/UCLA-style review is requested. Follow the [shared route and execution rules](../../../../docs/agent-skills.md#agent-execution) and [runbook](../../../../docs/runbook-e2e-mvp.md).

## Single rater or committee

For separate rating, `noharm.py rate PROJECT_PATH --item ITEM_ID --rubric RUBRIC_LABEL --backend BACKEND --model MODEL --reasoning-effort EFFORT` selects one authorized rater. Use the receiving coding agent and already agreed model for Local Mode. Omit backend only when an authorized `--committee default|PATH` is intended. An explicit backend cannot combine with a nondefault committee. Committee JSON supports `claude`, `codex`, legacy `subscription`, and `openrouter`. The bundled default committee includes paid calls. Inspect the specific status file and retain failed artifacts; do not change a passing or reviewed rubric to repair a failure.

## Text rubric ratings

The stored format selects the rating contract. For the text rubric format, independently rate C1 usual-care score and severity, and every item's score and severity, including `.0` omissions and add-ons. Preserve criterion/item IDs, item wording and `addOn` roles. Do not derive severity from appropriateness or convert the rubric to answer-table.

Use scores 1-9 and severity `none`, `mild`, `moderate` or `severe`, relative to the best option. A score of 1 requires at least moderate severity; scores 2-3 require at least mild. These floors are hard constraints for LLM ratings. Every `.0` severity must be at most C1 severity. Reject inconsistent ratings rather than silently capping them. Analysis tags are not rated or scored. Do not reuse legacy exclusions for precautions or additional testing/treatment: each text rubric omission is rated explicitly.

Generation-linked rating may apply a passing aggregate while retaining individual votes and provenance. Standalone `rate` remains advisory and does not edit the rubric or create a clinician review. Retain the bound rubric/task/prompt/schema hashes, individual votes, failures and LLM-generated authority; agreement is not clinician consensus. When authorized, a model may integrate draft pipeline output; candidate model responses remain independent and never pass through an integrator.

RAND panel modes are not implemented for text rubrics and must fail before provider calls. Do not substitute the legacy panel contract.

## Legacy RAND/UCLA-style review

For historical answer-table rubrics, optional RAND/UCLA-style LLM review uses `rate --method rand-quick` or `rate --method rand-full`, with `--committee AUTHORIZED_PANEL_PATH --tag FRESH_TAG` on an existing rubric. It requires an explicit panel with at least three members and defaults to one repeat. Resolve all panel and moderator routes and spend before calling: quick makes N logical model calls per repeat; full makes 3N+1. Quick is one independent rating round with median and disagreement checks. Full includes discussion and a second rating round. The legacy `rand` method aliases full. See the runbook for optional evidence, moderator, and worker settings. All executed phases are preserved. Full includes first ratings, member discussion, neutral moderator synthesis, and independent second ratings; quick does not use a moderator. All options receive 1-9 appropriateness ratings; usual-care and omission harm retain the historical exclusions. Median and IPRAS disagreement results are advisory sidecars, never silently applied to the rubric or described as clinician consensus. Inspect the Markdown report, individual votes, and failed receipts. Any failed member or moderator stops later phases. Preserve interrupted runs and select a new tag before another authorized attempt. Do not use the bundled default committee implicitly for this method. Do not apply this legacy panel contract to text rubric.

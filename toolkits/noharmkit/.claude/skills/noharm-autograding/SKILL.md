---
name: noharm-autograding
description: Map stored NOHARM model responses onto a chosen rubric and inspect judgment failures or stale inputs. Use for autograding, including reruns after rubric review.
---

Read `docs/agent-skills.md`, `docs/runbook-e2e-mvp.md`, and `docs/PROJECT_CHARTER.md`. Resolve the project, rubric label, backend/model, and authorized spend. Verify the chosen rubric passes for every case being judged. Do not silently substitute an older draft for a missing reviewed version.

```bash
.venv/bin/python tools/noharm.py judge PROJECT_PATH --rubric RUBRIC_LABEL --backend BACKEND --model MODEL
```

On projects using the current grading, judging without `--backend` defaults to the default judge in `pipeline/e2e/pipeline_v2_defaults.json`: direct `openai` with `gpt-6.1-sol` at `high` effort (needs `OPENAI_API_KEY`). On earlier projects it defaults to `openrouter` with `openai/gpt-6.1-sol` and `high` reasoning effort. Subscription alternatives are `--backend claude --model opus` or `--backend codex --model gpt-6.1-sol`. Optional `--reasoning-effort` applies to Codex/OpenRouter/OpenAI and defaults to `high` for judging. Follow the shared model-route rules.

Text rubrics use the earlier judge and the deterministic scorer. The command selects the path from the stored rubric format; do not convert the rubric to answer-table. The earlier judge receives a blinded rubric with criterion and item IDs and wording. It must not see `.0` omission rows, appropriateness scores, severities, usual-care ratings, analysis tags or add-on flags. Those belong to deterministic scoring, not evidence mapping. Keep the original model response unchanged and require literal evidence for recommended items. Later-care advice is mapped as `fallback`; an offered alternative is still recommended advice and counts in the scorer.

The judge does not assign or repair scores, severities, criterion roles or rubric wording. A response that recommends only add-ons does not fulfill the criterion; the scorer applies the omitted main approach. Do not invent a main approach or hide an unmatched statement to improve a score. Unknown ratings, unresolved rubric notes or stale content bindings block scoring. Stored legacy answer-table rubrics retain their existing judge and scorer behavior.

Projects created now use the study's pipeline. There the judge and scorer use one shared rubric per case (the latest reviewed clinician rubric, else the project's base rubric), so pass `--rubric` only to choose the base once. Related paid stages show a plan first and call a provider only with `--yes`: `rate-slots` (model raters rate the shared rubric), `severe-review` (a second model rechecks readings whose median worst error is severe), and `upgrade --base-rubric RUBRIC_LABEL` (moves an existing project; shows a cost estimate first). Ask for approved spend before any `--yes`. Projects not yet upgraded keep the earlier judge and scorer.

Labels are project-local `runN` or `reviewed-REVIEWER`. The command judges the project's stored responses across its declared trials, not one case. If only a subset was requested, explain that scope and resolve it before running unrelated cases. Inspect existing outputs before invocation: without `--resume`, the command refuses any existing judgment destination, including failed or stale receipts. Preserve those outputs. Changes to tasks or solutions, or separately authorized rejudging, require a fresh project/run. Do not delete or relabel old receipts to bypass the guard. A snapshot does not create a fresh run; follow the shared preservation rules and runbook recovery limits.

For the direct OpenAI API, use `--backend openai --model gpt-6.1-sol --reasoning-effort high` with an authorized model and spend. This route requires `OPENAI_API_KEY`, uses unprefixed OpenAI model IDs, and records token usage and request IDs. The CLI refuses a missing key before creating judgment receipts. Dollar cost remains unknown when the API does not supply it.

For an interrupted direct OpenAI run, take a snapshot before using `--resume`. Resume verifies each saved receipt's case, response, rubric, prompt, provider schema, backend, model, and reasoning effort before making calls. It retains passing and failed receipts unchanged and runs only missing jobs. It does not retry or repair failed judgments. Other backends reject `--resume`; changed bindings or unresolved receipts also block it. Worker count and transport timeout may change without changing the saved judgment identity.

Verify per-response status and input hashes in `results/judge/`. Report failed, missing, and stale mappings separately. Keep adequacy, harm events, and review status separate. Do not change rubric grades or invent clinician approval. Open Autograding for inspection; score only when that work was requested.

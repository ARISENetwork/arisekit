---
name: noharm-responses
description: Collect model responses for a named NOHARM benchmark, preserving model, trial, and response identity. Use to run candidate models on imported cases.
---

Read `docs/agent-skills.md` and `docs/runbook-e2e-mvp.md`. Resolve the project, full model set, trial count, backend, route-specific model IDs, and authorized spend before inference. Verify imported cases exist and prompts exclude the solution.

```bash
.venv/bin/python tools/run_inference.py PROJECT_PATH --backend api --model MODEL_A --model MODEL_B
```

The default `api` route uses LiteLLM. Other routes are `claude` (for example `--model opus`), `codex` (`--model gpt-6-astra`), and `openrouter` (`--model openai/gpt-6-astra`). Follow the shared model-route rules. Optional `--reasoning-effort` applies to Codex/OpenRouter; `--model` remains required for every route.

Use as many `--model` arguments as needed for the chosen set. Pass the complete intended model set together; do not silently relabel an existing campaign by narrowing its declared models or changing response identity.

Check the exit status and response/error records under `results/responses/`. Compare requested case/model/trial coverage against stored outputs, using cases × declared models × declared trials. Preserve failures and report gaps; a file alone does not mean complete coverage. Direct the user to Responses. Stop at response collection unless downstream work was requested.

Collect one response per case/model/trial. Omitted `--trials` uses `provenance.trials`, defaulting to 1. Before first collection, `--trials N` may set a positive count. A changed count is rejected once collection records exist; use a new project/run and preserve existing records and trial identifiers. Judging, scoring, and viewer coverage use the project count.

## Named response prompts

Add `--prompt NAME` (a saved prompt name or ID) to collect the same models with a saved prompt. Each model then gets its own response set named `MODEL+PROMPT_ID`, beside its unprompted set, and the leaderboard shows them as separate rows. The prompt text goes before the Task in the user message; there is no system prompt. `--prompt` and `--prompt-file` cannot be combined, and `--prompt` is refused on a project already collected with `--prompt-file`.

Prompts are saved in the project's `prompts.json`, from the Responses page dropdown ("New prompt...") or the project files. NOHARMKit ships no prompt text. A prompt locks once any response set uses it: its text cannot be edited or deleted, so save changes as a new prompt. Prompted sets can be added after unprompted collection; existing sets cannot be changed or removed.

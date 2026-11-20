# NOHARMKit

Use `ARISEKit` for the app name and `NOHARMKit` for the benchmark toolkit in documentation and user-facing text.

A portable, local severity-weighted benchmark toolkit with clinical prompt and policy defaults. Start with [README](README.md), [agent setup](docs/agent-skills.md), and [the pipeline runbook](docs/runbook-e2e-mvp.md). Clinical changes follow [the project charter](docs/PROJECT_CHARTER.md).

Use Task, Solution, Model response, and Case as defined in [README](README.md#terminology). Preserve legacy storage keys, CLI flags, skill names, and existing records.

## Workflow

Create a named project, import user-supplied tasks and solutions, generate and review rubrics, collect one response per case/model/trial, judge using the selected rubric, then score deterministically. Use project-local `runN` or `reviewed-REVIEWER` rubric labels. Imports require `--inputs-dir`. The browser inspects and reviews files; the coding agent runs stages.

The demo contains only synthetic illustrative outputs. Local review creates a separate copy and records review provenance; saving is not proof of clinical acceptance. Never forge clinician approval. Generated, automated, unresolved, and stale results retain their status.

## Runtime

Use `.venv/bin/python` after approved environment setup with `uv`. The viewer uses Node and npm in `app/`. Do not replace existing environments or change credentials. Consult command `--help` and the runbook before execution. Provider calls require explicit scope and authorized routes/spend. Review stored failures rather than silently discarding them.

Generation, rating, and judging support `claude`, `codex`, `openrouter`, and direct `openai`; inference also retains its default `api` (LiteLLM) route. Claude Code and Codex subscription routes use account login, while API routes use configured keys. Direct OpenAI uses `OPENAI_API_KEY` and unprefixed model IDs. Resolve backend and route-specific model IDs before calls. Never silently fall back from a subscription error to an API. Legacy `subscription` means Claude; preserve stored records and provenance. See the runbook for defaults and reasoning effort.

## Rubric editor ownership

The rubric editor is noharm-science's `harmreview/` (local sibling `../noharm-science`). Keep the toolkit on its latest commit. Shared editor layout, controls, rubric-editing behavior, and the guide belong there first. Preserve its full interface; do not build a competing editor or make independent changes to the synced copy in `app/harmreview/`. The legacy answer-table editor stays pinned to the read-only noharm-kit archive (`../noharm-kit`), its final source.

This repository owns its routing, project-storage adapters, save safeguards, host notices, and the pinned validation in `lib/rubric-text-v2.ts`. They reach the synced editor through the host in `components/TextV2RubricEditor.tsx` and a small checked integration patch. Keep those differences explicit and outside the shared editor where practical. Do not overwrite them during synchronization. Record any necessary exception rather than silently introducing drift.

Both pins, allowlists, and integration patches are recorded in [app/upstream](app/upstream/README.md). Users need no access to either reference repo. Run `.venv/bin/python tools/sync_harmreview.py check` for offline drift detection; the frontend `check` command includes this guard. Maintainers update with `update --source noharm-science --repo ../noharm-science --ref COMMIT`, rebuild a hand-resolved patch with `record`, and prove it with `verify`. Review the imported diff, exercise the editor, and run local checks before committing; synchronization does not run automatically.

## Response collection

`tools/run_inference.py` stores one response per case/model/trial. Project `provenance.trials` defaults to 1 and governs collection, judging, scoring, and viewer coverage. Set it with `create --trials N` or at first collection with `run_inference.py --trials N`; omitted collection counts use provenance. Once collection records exist, changing the count requires a new project/run. Preserve existing trial identifiers and the declared model scope.

Keep canonical agent skills in `.claude/skills/`; preserve relative `.agents/skills/` aliases. Keep complete run identities and use fresh artifacts when prompts, tasks, solutions, schemas, models, or configuration change.

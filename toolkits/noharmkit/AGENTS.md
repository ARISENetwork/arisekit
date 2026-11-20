# Toolkit agent instructions

## ARISEKit integration

This toolkit is pinned inside `toolkits/noharmkit` of the ARISEKit checkout.
Treat this directory as the toolkit root, including its `projects/`, `skills/`,
and canonical `.claude/skills/`. Read [INTEGRATION.md](INTEGRATION.md).
Reuse the shared `../../scripts/dev/.venv/bin/python` when the toolkit-local
`.venv` does not exist. For commands in the stage skills, substitute that
interpreter for `.venv/bin/python`. Do not install a second environment just
to run a stage. The parent checkout also exposes `scripts/noharm.py` as a CLI
entrypoint. Launch the integrated app from the parent checkout with `npm run dev`.

The original standalone instructions follow.

Read [CLAUDE.md](CLAUDE.md) and the [project charter](docs/PROJECT_CHARTER.md) before clinical workflow changes. Use the canonical stage skills in `.claude/skills/`; `.agents/skills/` contains relative aliases for Codex.

`ARISENetwork/noharm-kit` is the reference implementation for the rubric editor interface. Make shared editor changes there first, then bring a reviewed, commit-pinned update here. Keep toolkit-specific routing, project storage, and integration separate; do not independently redesign or change the copied editor. See the rubric editor ownership section in [CLAUDE.md](CLAUDE.md).

Use Task, Solution, Model response, and Case as defined in [README](README.md#terminology). Preserve legacy storage keys, CLI flags, skill names, and existing records.

Work only in the user's named project and within the requested scope. Preserve source wording, existing records, and provenance. Do not infer the agent's project from browser selection. Inspect before editing; use the project Python environment. Ask before installing dependencies, deleting files, changing schemas, or modifying credentials. Resolve model routes and authorized spend before live calls; do not reconfirm already authorized runs.

The bundled demo is synthetic. Never represent it, model-generated solutions, saved drafts, or automated review as clinician validation. Keep one response per case/model/trial. `provenance.trials` declares the positive trial count, defaulting to 1; preserve stored trial identifiers. Set the count at creation or before first collection, and use a new project/run to change it after collection records exist. Changed prompts or tasks require new identities, not relabeling old output. Preserve failures and report incomplete coverage.

Use [the runbook](docs/runbook-e2e-mvp.md) for runnable commands. Verify exit codes and output status. Run relevant local checks before claiming completion. Do not install or call providers merely to test documentation.

# Agent skills

Open the `toolkits/noharmkit` directory in Codex or Claude Code and type `startup`. If skills
are missing, start a new session in the repository. Explicit shortcuts are
`$startup` in Codex and `/startup` in Claude Code. No separate skill installation
is required. See [First launch](../README.md#first-launch).

## Manual setup

From `toolkits/noharmkit` on macOS or Linux, check Python 3.11 or newer, uv,
Node.js 22 or newer, and npm. Reuse an existing environment. After approving installation:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ../.. -r requirements.txt
npm ci --prefix app
.venv/bin/python tools/noharm.py view
```

`-e ../..` installs the shared `arisekit` package from the ARISEKit repository root. An environment
that reports `No module named 'arisekit'` predates this; rerun the `uv pip install` line once.

Keep the terminal running and open [localhost:9000](http://localhost:9000/).
Use `view --port 9001` if busy; stop with Ctrl+C. Follow
[STARTUP.md](../STARTUP.md) for local startup and verification.

## New projects

Choose **New Project**, or ask:

```text
Use noharm-new-project to create a project called my-benchmark.
```

Dataset accepts typed cases and CSV/JSON uploads. Original uploads stay unchanged
and show Awaiting processing until linked to imported cases. Generate Rubric
saves typed data and opens the coding-agent prompt. After import, Add Case and
Bulk Upload remain available. Cases are editable until rubric attempts or
responses exist; later changes need a new case identity. Source history and
conflict checks protect prior data. Header Next links only navigate.

To continue, ask `Use noharm for my-benchmark and run the next pipeline step.`
After the agent finishes, click Refresh and select the project.

New generation defaults to the text rubric format. In Local Mode, use the
receiving coding agent and already agreed model, passing backend and model
explicitly. Read the [current authoring rules](contracts/rubric-authoring-rules.md)
before drafting. C1 is usual care, C2 follow-up, and every criterion has an
explicit `.0` omission. Main approaches and `addOn: true` extras each have
appropriateness and error severity ratings. LLM drafts and ratings enforce
severity floors; human review can retain visible floor warnings.

The earlier judge maps response evidence from a blinded rubric; the scorer computes native error
severity, bounds and optimal status. Do not use legacy F1 for text rubrics.
`generate --format answer-table` selects historical compatibility explicitly.
Do not rewrite existing records or pass legacy authoring rules into text rubrics.

| Skill | Purpose |
| --- | --- |
| `startup` | Launch the viewer |
| `noharm-new-project` | Create a project |
| `noharm-import-cases` | Import supplied tasks and solutions |
| `noharm-rubrics` | Generate and review rubrics |
| `noharm-responses` | Collect model responses |
| `noharm-autograding` | Map responses to the selected rubric |
| `noharm-scores` | Compute scores and coverage |
| `noharm` | Inspect or run requested stages |

<a id="case-inputs"></a>

## Dataset format

Follow [Data privacy](../README.md#data-privacy). For direct import, supply one
JSON file per case, named by ID, such as `Case001.json`:

```json
{
  "presentation": "Task presented to the evaluated model.",
  "recommendations": "Acceptable solution used to build the rubric."
}
```

Both strings are required; never invent a missing solution. Preserve source
wording, supplied IDs, and provenance. Without supplied IDs, use `Case001`,
`Case002`, etc., continuing after the highest existing number. Display names are
Case-001, Case-002. Do not derive names from content; IDs have no hyphens, path
separators, or `Ex` prefix.

For browser uploads, use Task, Solution, and Errors fields. In CSV, concatenate
acceptable alternatives in one Solution field with `SOLUTION:` separators.
Errors and pre-rated criteria are optional. Confirm mappings for other formats.

Legacy names remain: `presentation` = Task, `recommendations` = Solution,
Input = Task, Reference = Solution, item = Case. Keep `cases/`, `caseId`,
`case_id`, and existing records. Use `--item` and `--inputs-dir`; `--case` and
`--cases-dir` remain aliases. Policies and generation prompts remain clinical.

## Model routes

The coding agent does not determine the model backend. Choose the exact backend
and model together; do not substitute or fall back silently. Subscription routes
use installed CLI login; APIs use configured keys. Legacy `subscription` means
Claude. See [route defaults](runbook-e2e-mvp.md#model-routes).

## Agent execution

- Read repository instructions. Run from the root with `.venv/bin/python` and the [runbook](runbook-e2e-mvp.md).
- Resolve the named project, never browser selection, the newest folder, or every project. Projects live in `projects/`.
- Honor requested stages, sources, cases, rubric versions, models, trials, and spend. Resolve only missing or changed scope; retain prior authorization. One stage does not authorize downstream stages. Subscription-only permission excludes APIs and paid committees; the bundled committee includes paid OpenRouter calls.
- Use only authorized sources. Never print credentials, change environment files, or install CLIs solely to test setup. Synthetic data stays labeled synthetic.
- Store one response per case/model/trial. `provenance.trials` defaults to 1; set a positive count before collection. Once records exist, a changed count needs a new project/run. Preserve trial identifiers and model scope.
- Integrators reconcile draft pipeline outputs only when authorized. Collected candidate responses stay independent; never integrate them into another evaluated response.
- Changed tasks, solutions, prompts, models, schemas, code, or configuration need fresh identities. Preserve source wording and prior evidence; never relabel old outputs or fabricate clinician approval.
- Check prerequisites, exit codes, and per-record status. Keep logs in `results/` when present. Preserve failures and report missing, stale, and incomplete coverage with recovery actions. Files alone do not prove success.
- Ask before dependency installation, deletion, source replacement, or schema changes needed for recovery. Snapshot with writers paused; follow [recovery limits](runbook-e2e-mvp.md#identity-and-failures), never delete receipts to bypass guards.
- The viewer inspects and reviews files. Share verified links per STARTUP.md. Saving preserves the source and defaults to `reviewed-local`; existing reviewer namespaces remain usable. Clinical authority follows the [charter](PROJECT_CHARTER.md).

## Skill locations

Canonical skills are in `.claude/skills/`; relative `.agents/skills/` aliases
support Codex. Keep one copy. Discovery: [Codex](https://developers.openai.com/codex/skills/),
[Claude Code](https://code.claude.com/docs/en/skills).

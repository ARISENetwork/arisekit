# API implementation reference

Start with the [API execution guide](api-execution.md) for setup and everyday use.

API Mode uses OpenRouter for rubric generation, optional advisory harm rating,
models under test, and autograding. Scoring uses the existing deterministic
scorer. Local Mode retains coding-agent handoffs.

## Model setup

New API projects open `/noharm/api-setup`. Resuming an API project without a saved
setup opens the same page. The previous review URL redirects here.
Rubric generation, harm rating, and autograding require an integrator when two
or more contributors are selected. Models under test each respond independently
and never use an integrator. Harm rating is optional. Saving returns to Dataset
without executing any model calls. Local Mode and prepared examples cannot save
an API setup. Model setup is locked while a run is active or unresolved.

The picker opens on a curated Recommended list, with All models providing the
full searchable catalog. Both lists share selections. The shortlist contains
named models from major providers checked against the
[OpenRouter catalog](https://openrouter.ai/api/v1/models) and
[discovery page](https://openrouter.ai/discover) on 2026-10-25. It is an editorial
starting point, not evidence of performance in this pipeline. Only currently
available shortlist entries are shown. New setups preselect GPT 6.1 Sol as the
single autograding judge, with no integrator. Other stages start unselected,
and saved project configurations retain their existing choices.
Selected models and integrators expose independent reasoning levels when the
model supports them. The initial choice
uses the model default. Mandatory-reasoning models cannot select Off, and models
without effort selection show no level control. Explicit choices are validated
against the current catalog and sent independently for each stage and role.
The model default omits the reasoning argument. See
[OpenRouter reasoning metadata](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#discovering-per-model-reasoning-options).

## Responses display

In API Mode, the Responses page reads the selected response models and reasoning
choices from the same saved API setup used for execution. Explicit effort levels
are shown as selected. Unset effort uses the provider default reported by the
current catalog, with Model default as the fallback when metadata is unavailable.
Catalog failures retain the saved selections and collection status.

Collection status counts every imported item and declared trial for each selected
model. Missing responses are Pending, all expected responses present without
errors are Complete, and any stored response error is Failed. Partial collection
counts remain visible. A recorded route or reasoning setting that differs from
the current setup is Different settings with an explanation; existing responses
are retained and are not classified as provider failures.
Legacy records without route metadata remain readable. Judge and score status do
not change collection status.
Selected models and pending trials are available in the picker before collection
and remain selected when moving to Autograding or Scores.
Other saved responses remain accessible; this display does not replace or delete
them. Local Mode keeps its coding-agent model checklist.

## Local runtime

Use the repository's Python environment with the toolkit's existing dependencies.
The server locates that environment or uses `NOHARM_PIPELINE_PYTHON`. Model calls
require `OPENROUTER_API_KEY` in the server environment. The subprocess receives
only that provider key, not direct-provider credentials. No dependency or
credential installation is performed by the execution endpoint.

## Partial scoring

The score stage accepts `allowPartial`. It applies to scoring only. The stage
writes every scorable row and returns the coverage gaps it skipped, instead of
refusing the whole run. Finishing a judgment review uses it to rescore locally.

It works in Local Mode and without a saved model configuration, because scoring
makes no model calls.

## Workflow safeguards

New Project, Resume Project, and API model setup show execution availability
before a stage starts. Checks disclose only runtime and key presence, with no
provider call or secret value. Local deterministic scoring can run without a provider key.

Changing models under test or their reasoning after collection is rejected
before replacing the saved configuration. API setup explains the impact and can
create a separately named run with the proposed setup, original inputs, rubrics,
and source runtime pin. Responses, judgments, and scores are not copied. The
original project remains unchanged.

Closing the rubric popup or following a case/version/project link with edits
opens Save and continue, Discard edits, or Keep editing. A disabled or failed
save cannot silently discard the draft. The guard receives explicit editor
lifecycle callbacks through the documented toolkit integration patches. Source
pins and the canonical validators remain unchanged.

Model and coverage/error counts open the affected case, item, trial, rubric,
and status, with links to the appropriate stage. Empty results identify the next
unfinished stage. Selecting a reviewed rubric explicitly shows when existing
judgments still use an earlier version and offers case-scoped regrading.

Download leaderboard CSV exports the summary. Download project exports a
restorable tar.gz of project inputs, rubric versions, responses, judgments,
scores, configuration, receipts, and provenance. Its manifest records files,
byte counts, SHA-256 hashes, empty directories, and excluded categories. Credentials,
links, temporary/cache files, and restricted paths are excluded. Downloading reads the local project and makes no model calls.

## Recovery

Scoring status names the local deterministic route and explicitly states that
no model calls or API credits are used. Older score records use the same display.

Interrupted and failed runs with a saved job ID expose **Review saved work**.
A rejected start is shown separately with its setup error. A connection ending
before a job ID arrives asks the user to check saved status before retrying. Inspection copies the
project into a disposable workspace, blocks provider dispatch, and validates
the current stage identity and saved receipts using the execution checks. It
makes no provider calls and does not change the source project. New execution
records freeze that identity before starting a worker.

Recovery checks server-owned workspace metadata, local ownership,
the saved job ID, and whether its worker has stopped. A live worker or an
unverifiable worker state blocks recovery. Older runs without this metadata
still require manual inspection; their files are preserved.

Compatible work can resume after explicit confirmation. The server repeats the
inspection and verifies that the project, retained files, configuration, and
job have not changed since the review. Only verified saved outputs are reused;
remaining model calls use API credits. A complete cache can finish without
provider access. Publication conflicts use a three-way comparison with the
last acknowledged snapshot. Independent changes are retained; conflicting
files are never overwritten. Recovery records source-run and restoration
provenance, and the original execution workspace remains available.

Changed or failed stage outputs require **Start a new run**. This creates a
separate named project, opens its saved API setup, and makes no model calls.
The original project is unchanged. The copy retains source cases and dataset
inputs, plus artifacts from earlier pipeline stages. Autograding retries retain
rubrics and collected responses; scoring retries also retain judgments and
their web receipts. Failed current-stage and downstream outputs are not copied.
The new project records source identity and copied-file hashes. All execution
preflights still apply if copied earlier-stage artifacts are incompatible.

The scoring recovery identity includes the current scorer, validator, judge
rules and schema source hashes. An upstream change cannot silently reuse an
earlier recovery identity. The scoring policy is unchanged.

## Checkpoints

Each job runs in an isolated local directory. After every receipt, the driver waits for the server to save the checkpoint to the project.

**Stop after current call** requests a stop without closing the connection.
The interface shows Stopping until the current call is checkpointed, then no
next call starts. Stop requests must match the project and saved job.
Closing the page also stops execution at the next completed checkpoint. Explicitly
re-running the same action reuses matching, verified receipts. Saved model
failures remain failures and are not silently retried. Changed inputs or model
configuration must preserve existing evidence.

A conflicting project edit stops publication and retains output in the execution
directory shown in the error. An unresolved process crash blocks new execution
until its retained output is inspected. Do not clear the status or retry blindly,
because an unpublished model response may already have consumed credits.

<details>
<summary>Developer checks and historical execution evidence</summary>

# Rubric pipeline runbook

Run commands from the NOHARMKit directory (`toolkits/noharmkit`) with `.venv/bin/python`. For setup, see
[First launch](../README.md#first-launch). Use authorized data and routes per
[Data privacy](../README.md#data-privacy). Clinical authority follows the
[charter](PROJECT_CHARTER.md). New rubrics follow the
[text rubric contract](contracts/rubric-text-v2.md) and
[current authoring rules](contracts/rubric-authoring-rules.md), with the earlier judge
and scorer for older projects; new projects use the
[pipeline grading](#pipeline-grading) below. Historical answer-table records retain the
[legacy contract](contracts/answer-table-rubric-v1.md).

## Model routes

Choose backend, exact model ID, and spend before live calls. CLI routes use
account login; APIs use keys. Availability and account limits apply. Examples
are templates, not live verification. Subscription failures never fall back to APIs.

| Stage | Default backend | Default model | Other backends |
| --- | --- | --- | --- |
| Generate | `claude` | `opus` | `codex`, `openrouter`, `openai` |
| Rate | Bundled committee | Configured members | Explicit single-rater backend |
| Inference | `api` (LiteLLM) | Required `--model` | `claude`, `codex`, `openrouter` |
| Judge | `openrouter` | `openai/gpt-6.1-sol` | `claude`, `codex`, `openai` |

- Generation defaults: Claude `opus`, Codex `gpt-6-astra`, OpenRouter `openai/gpt-6-astra`, direct OpenAI `gpt-6.1-sol`.
- Judging defaults: GPT-6.1 Sol on OpenRouter, Codex, and OpenAI; Claude retains `opus`. Omitted reasoning effort is `high` on Codex/OpenRouter/OpenAI.
- `--reasoning-effort` applies to Codex, OpenRouter, and OpenAI. Direct OpenAI uses `OPENAI_API_KEY` and unprefixed IDs; cost stays unknown if absent from the response. Inference always requires `--model`.
- Legacy `subscription` means Claude. Preserve stored backend values and identities.
- If the agent shell blocks networking, request tool approval for the exact authorized command. Preserve subscription worker sandbox and authentication.
- Codex requires exit zero, a completed turn, and nonempty final text. Earlier recovered connection errors are retained. Incomplete turns, tool use, unknown events, and malformed streams fail; transport success does not establish rubric validity.

## Create and import

Supply one JSON file per case with nonempty `presentation` (Task) and
`recommendations` (Solution); see [dataset format](agent-skills.md#dataset-format).

```bash
.venv/bin/python tools/noharm.py create projects/my-benchmark
.venv/bin/python tools/noharm.py import projects/my-benchmark --item Case001 --inputs-dir /path/to/my-inputs
```

Create refuses existing folders. `--trials N` declares a positive trial count,
default 1. Import requires a source directory. Identical imports preserve files;
changed source or collection records are refused. Use a fresh identity for
changed data. Legacy `--case` and `--cases-dir` remain aliases.

## Project snapshots

Pause writers and choose a new destination under an existing parent:

```bash
mkdir -p snapshots
.venv/bin/python tools/noharm.py snapshot projects/my-benchmark snapshots/my-benchmark-before-review
```

Copies every file and folder unchanged into a new destination outside the project;
an existing destination is never replaced. A snapshot is a backup, not a new run
or approval.

## Generate and review

```bash
.venv/bin/python tools/noharm.py generate projects/my-benchmark --item Case001 --format text-v2 --runs 1 --backend claude --model opus --committee none
```

Generation defaults to text rubrics and Claude without a committee. In Local Mode,
pass the receiving coding agent and already agreed model explicitly instead
of switching routes to match an example. Inspect
`answer-tables/Case001.run1.status.json`, then open Rubrics and the full editor.
Saving creates `answer-tables/<ID>.reviewed-<reviewer>.json` and a review record,
preserving `runN`. Local review defaults to `reviewed-local`. Select that exact
label for subsequent rating or judging. Review authority is content-bound.

Text rubric uses C1 usual care with `score` and `harm`, C2 follow-up first, and
ordinary criteria beginning at C3. Every criterion includes a `Cn.0` omission
item with fixed text and explicit ratings. Main approaches are complete courses;
`addOn: true` items are extras that never fulfill the criterion alone. Each
item has appropriateness 1-9 and severity none, mild, moderate or severe,
measured against the best option. Severity is explicit, never score-derived.
LLM drafts and ratings enforce the severity floors: score 1 at least moderate,
scores 2-3 at least mild. Human review retains floor violations as warnings.
Every omission severity must be at most usual-care severity. No legacy harm
overrides, activation fields, tag arrays or additional catch-all criteria are
added to new drafts. Tags use one analysis-only `tag` value.

Generation starts at `run1`; `--start-run N` selects a fresh positive starting
run number. An existing failed, imported or legacy slot is preserved, not
overwritten. Reuse requires the same verified passing generation identity.
Changed tasks, solutions, prompts or configuration require a fresh project/run.
Draft null ratings or unresolved notes can be reviewed in the editor, but they
block scoring. Structural validity does not establish clinical validation.

### Expert review files

Portable review supports legacy answer tables and text rubrics, including
mixed-format projects. Each case opens its existing format's editor. Text rubric
assignments carry only the project's judge/scorer source pin for validation,
retain native rubric hashes and Main approach/Add-ons roles, and import through
the same separate-reviewer workflow. Human-edited unknown ratings and unresolved
notes remain drafts and cannot be scored until resolved. Changed source text,
rubric content, or validation pins require a fresh assignment.

On Rubrics, select a passing version and choose **Export Editor HTML**. Send the
downloaded file to each expert. It contains that rubric and its Task and Solution,
with its existing format's editor. Legacy answer tables include Guide and Score
Preview. It opens offline without an app installation or account. Each expert enters a distinct reviewer ID, edits their
own copy, and chooses **Download Review**. The downloaded HTML includes their
reviewer ID, edits, and editing history. Reopening that file continues directly
in the editor, without entering an ID or choosing Resume. Changes are held in
the tab until downloaded; browser storage is not required. Keep the latest
download rather than reopening the original blank assignment.

Choose **Export Project HTML (VERSION)** to include every case in one file, using
that same rubric version for all cases. Export refuses missing or invalid rubrics
instead of skipping cases. Each expert uses the case selector or Previous/Next
controls and chooses **Save Case**, including for unchanged rubrics. Unsaved edits
must be saved before switching cases. **Download Review** keeps all saved cases
in one HTML file and remembers the current case. Partial downloads reopen in
that same file; every assigned case must be saved before the file can be
imported. The returned HTML preserves each case's source version, content
identities, edits, and editing history. Imports extract only the embedded review
data, without running the HTML, and retain the whole project submission as well
as each individual expert copy. Previously downloaded JSON submissions remain
importable.

Choose one or more returned files under **Import returned reviews**, inspect the
preview, and click **Import Expert Copies**. Imports create separate
`reviewed-REVIEWER` versions and preserve original submissions under
`expert-reviews/`. They refuse changed source rubrics or case text, mismatched
projects, invalid rubrics, and existing reviewer copies with different content.
Repeating the identical import adds nothing. Use a unique reviewer ID for each
independent submission. Reviewer IDs are self-declared, not authenticated.

Experts can complete the downloaded HTML offline. Import returned reviews into the same local project.

The app's development, build and test commands compile the portable editor shell.
Export only inserts the selected case data into that shell; production does not
need a runtime compiler or editor source files. After changing the editor during
a running development session, run `npm run build:portable` from `app/` to refresh
the shell. Generated `portable/editor-shell.json` is not committed.

Export and import do not reconcile experts' edits, establish consensus, or change
which rubric existing judgments use. Select the intended reviewed version for
subsequent stages. Share files only through channels appropriate for their case
content.

Historical generation retries and replaced reviews retain original bytes under
`answer-tables/history/CASE.VERSION/UNIQUE_ID/`. Keep one writer per project;
individual replacements are atomic, but rubric, status, and review log are not
one transaction.

Optional generation-linked rating uses `--committee default|PATH`. Inspect and
authorize members first: the bundled committee includes subscription and paid
routes. Text rubric rating independently rates usual-care appropriateness and
severity and every item's appropriateness and severity, including omissions
and add-ons. IDs, wording and add-on roles stay fixed. A passing generation-linked
aggregate may apply ratings while retaining individual votes. Floors and the
usual-care omission ceiling are hard constraints for LLM ratings; conflicts
fail instead of being silently capped.
Standalone rating is advisory and does not update the rubric or editor:

```bash
.venv/bin/python tools/noharm.py rate projects/my-benchmark --item Case001 --rubric run1 --repeats 1 --backend BACKEND --model MODEL --reasoning-effort EFFORT
```

`--rubric` selects a version; rating also accepts `--table`. Explicit `--backend`
selects one rater and cannot combine with a nondefault committee. Without it,
`--committee default|PATH` applies. Committee JSON uses `{backend, model,
reasoning_effort?}` and supports the public backends, including `subscription`.
Repeats test rater reliability, not candidate responses. Outputs go to
`results/ratings/TAG/`; preserve existing tags and use a new tag for rerating.
Tags are 1-64 letters, digits, underscores, or hyphens, starting with a letter or digit.

### Legacy answer-table compatibility

Explicit `generate --format answer-table` retains historical authoring and
rating behavior. Its D1 follow-up, return-precaution and additional-testing/
treatment rules, tag arrays, activation fields and score-derived harms belong
only to that path. Preserve existing records, judge profiles and scoring rules;
do not convert them to text rubrics in place.

### Legacy RAND/UCLA-style LLM panel

For answer-table rubrics, an advisory adaptation of [RAND/UCLA](https://www.rand.org/pubs/monograph_reports/MR1269.html),
not a clinician consensus reference. Supply an authorized committee with at
least three members; RAND modes never implicitly choose the bundled committee.

| Mode | Process | Logical calls per repeat |
| --- | --- | --- |
| `rand-quick` | Independent ratings | N |
| `rand-full` | Ratings, discussion, moderator, private rerating | 3N + 1 |

```bash
.venv/bin/python tools/noharm.py rate projects/my-benchmark --item Case001 --rubric run1 --method rand-quick --committee /path/to/authorized-panel.json --tag quick-test
.venv/bin/python tools/noharm.py rate projects/my-benchmark --item Case001 --rubric run1 --method rand-full --committee /path/to/authorized-panel.json --tag full-test --evidence /path/to/supplied-evidence.md
```

- `--evidence` supplies text; absent evidence is recorded, never searched or invented.
- Full's moderator defaults to the first member; override with `--moderator-backend`, `--moderator-model`, and optional `--moderator-reasoning-effort`. Quick rejects moderator flags.
- RAND defaults to one repeat; committee to three. `--workers` limits concurrent members; repeats run sequentially. Retries add attempts. Repeated routes do not represent distinct experts.
- Full rerates every option using individual first ratings, distributions, reasons, discussion, and neutral synthesis. Agreement is never forced.
- Appropriateness uses the true median. P30/P70 use linear interpolation at `(N-1)*p`. IPRAS disagreement is `P70-P30 > 2.35 + 1.5*abs((P30+P70)/2 - 5)`. Disagreement means uncertain; otherwise medians 1-3 are inappropriate, 7-9 appropriate, intermediate values uncertain. Lack of disagreement is not consensus.
- Harm uses the lower categorical median for even counts; a span of two tiers flags disagreement. Return precautions, additional testing, and additional treatment stay excluded from omission-harm rating, but receive appropriateness ratings. Results never automatically change grades, overrides, or usual-care caps.
- Reports, raw phase receipts, evidence, identities, reasons, and failures are retained under `results/ratings/TAG/`. A failed member or moderator stops later phases. Existing or interrupted outputs block reuse; choose a fresh tag. Results do not appear in the editor or create clinician review.
- `--method rand` aliases full, retaining the legacy `committee` tag. Other default tags are `rand-quick` and `rand-full`.

This is the legacy panel contract. Text rubric uses format-aware independent rating
with explicit scores and severities; do not apply the historical omission
exclusions or convert text rubrics to use this panel. RAND modes reject text rubrics
before provider calls because its panel protocol is not implemented.

## Collect responses

```bash
.venv/bin/python tools/run_inference.py projects/my-benchmark --backend api --model MODEL_A --model MODEL_B
```

Pass the complete intended model list; preserve existing declared scope. Each
case/model/trial gets one response, excluding solutions from candidate prompts.
`--trials N` can set a positive count before any collection records exist;
otherwise it uses `provenance.trials` (default 1). Changing the count afterward
requires a fresh project/run. Inspect failures and missing coverage.
An integrator may reconcile rubric drafts or other authorized draft pipeline
output. It never combines these candidate model responses.

## Named response prompts

Add `--prompt NAME` (a saved prompt name or ID) to collect the same models with a saved prompt. Each model then gets its own response set named `MODEL+PROMPT_ID`, beside its unprompted set, and the leaderboard shows them as separate rows. The prompt text goes before the Task in the user message; there is no system prompt. `--prompt` and `--prompt-file` cannot be combined, and `--prompt` is refused on a project already collected with `--prompt-file`.

Prompts are saved in the project's `prompts.json`, from the Responses page dropdown ("New prompt...") or the project files. NOHARMKit ships no prompt text. A prompt locks once any response set uses it: its text cannot be edited or deleted, so save changes as a new prompt. Prompted sets can be added after unprompted collection; existing sets cannot be changed or removed.

## Judge and score

Select `runN` or the exact saved `reviewed-REVIEWER` rubric for every case:

```bash
.venv/bin/python tools/noharm.py judge projects/my-benchmark --rubric reviewed-local --backend openrouter --model openai/gpt-6.1-sol --reasoning-effort high
.venv/bin/python tools/noharm.py score projects/my-benchmark
```

Direct OpenAI example:

```bash
.venv/bin/python tools/noharm.py judge projects/my-benchmark --rubric run1 --backend openai --model gpt-6.1-sol --reasoning-effort high
```

API judging defaults to 24 concurrent calls, subscriptions to 8; `--workers N`
overrides. API timeout defaults to 120 seconds per attempt, or 1800 seconds
(the study judge's) on projects using the current grading; `--timeout N`
overrides. Transport failures allow two retries; failed evidence is never
repaired by retry. Text rubrics dispatch to the earlier judge: it sees criterion/item IDs and
wording, with `.0` omission rows, ratings, tags and add-on flags excluded.
The judge maps quoted evidence without changing rubric scores or severities.
An offered alternative still counts as recommended advice; later-care advice
is mapped as `fallback`. The scorer handles the corresponding severity and omission
rules deterministically. Legacy answer-table judging keeps its existing path.
Direct OpenAI enforces strict JSON schema and records raw replies and schema hash;
evidence validation still applies. Completed receipts flush individually.

Judgments go to `results/judge/`; existing receipts block rejudging. Direct
OpenAI `--resume` verifies case, response, rubric, prompt, provider schema,
backend, model, and effort, then fills only missing jobs. Passing and failed
receipts stay unchanged. Worker count and timeout may change; identities may not.
Snapshot first. Other backends do not support verified resume. There is no
automatic fork or judgment-run selector; use a new project/run for changed inputs
or another judging run.

Scoring makes no model calls and writes `results/report.md`. Expected coverage
is cases × declared models × declared trials, with no scoring trial override.
Means average eligible trial responses, not per-case means or best-of-N. Missing,
stale, or unverified bindings block scoring. Use `--allow-partial` only for
explicitly requested development reports, keeping gaps visible.

### Reporting

For text rubrics, report the scorer's error severity and lower/upper error bounds, optimal
status, omission and commission events, coverage and evidence status. Every
actionable recommended item contributes its severity, including alternatives;
`fallback` later care is excluded. No complete main approach triggers `.0`
omission, even if add-ons are present. Each criterion takes the worst error;
actionable unmatched advice can leave a severe upper bound. A case is optimal
only when the upper error bound is none. Do not manufacture Recall, Precision
or F1 from the scorer, or combine the scorer and legacy F1 into one comparison.

For historical answer-table results, retain Recall, Precision, F1 and their
original harm definitions. Incomplete coverage can alter case weights; retain
denominators and gaps for either format. Missing or failed responses are not
zero errors or optimal cases. Provisional or unresolved records stay labeled.
Review status is separate from judgment authority; statistical claims follow the
[charter](PROJECT_CHARTER.md#evidence-and-reporting).

## Pipeline grading

New projects grade text rubrics with the study's pipeline. Older projects keep
the earlier judge and scorer until you run `upgrade`. On these projects
`judge` and `score` work as above, with these differences:

- The judge and the scorer use one shared rubric per case: the latest reviewed
  clinician rubric, else the project's base rubric. Pass `--rubric` only to
  choose the base once; later runs refuse a different one.
- Each case has at least three rater slots. A clinician's saved review fills
  a slot with their own ratings. Remaining slots are filled by model raters in
  the fixed order `sol`, `gemini`, `opus`. A rating counts only while the item's
  text is unchanged.
- A response's worst error is the median over the slots. F1 is reported beside
  it. With an even number of slots, ties take the less severe value; set
  `settings --tie-rule more` to take the more severe one.
- A grade is final only when every slot has rated every item and no severe
  review is waiting. Scores that are not final stay visible and are marked.

Every stage below shows its plan and calls no provider until you add `--yes`.

```bash
.venv/bin/python tools/noharm.py rate-slots projects/my-benchmark --rubric run1
.venv/bin/python tools/noharm.py rate-slots projects/my-benchmark --rubric run1 --yes
.venv/bin/python tools/noharm.py judge projects/my-benchmark --backend openai --model gpt-6.1-sol
.venv/bin/python tools/noharm.py severe-review projects/my-benchmark
.venv/bin/python tools/noharm.py severe-review projects/my-benchmark --yes
.venv/bin/python tools/noharm.py score projects/my-benchmark
.venv/bin/python tools/noharm.py settings projects/my-benchmark --tie-rule more
```

- `rate-slots` asks each model family to rate only the items that lack a current
  rating. `--route FAMILY=BACKEND/MODEL[@EFFORT]` overrides a family's route.
  Failed ratings are kept and never used.
- `severe-review` rechecks each response whose slot-median worst error is severe
  and whose slots are complete. The corrected reading replaces the judge's for
  scoring. `--route BACKEND/MODEL[@EFFORT]` overrides the review route.
  Responses with a severe median and no review are marked "severe review pending".
- `score` makes no model calls. Rows are marked when the judge or review used a
  model other than the study's.
- `upgrade --base-rubric run1` moves an existing project: it rates the slots,
  re-judges every response, runs severe reviews, and scores, after showing a cost
  estimate (`--prices FILE` supplies prices). Old judgments, ratings, and scores
  stay on record, labeled as the previous pipeline. `--route STAGE=...` overrides
  a route (stages: `sol`, `gemini`, `opus`, `judge`, `review`).
- `settings --tie-rule less|more` sets the even-count tie rule.
- `replace-outdated` (with `--dry-run` to preview, `--case ID` to limit) moves
  outputs an edit to the case text put out of date to `results/superseded/`:
  responses collected for an earlier Task (with their judgments and scores) and
  judgments made against an out-of-date rubric (with their scores), plus the
  report. The case can then be collected, judged, and scored again in the same
  project. After an edit, a case is judged against the newest rubric generated
  since.

## Identity and failures

Generation reuse checks rubric/hash and exact inputs; inference checks model
and prompt; judgments bind task, response, and rubric. Changed data, prompts,
code, schemas, models, or configuration need fresh identities. Preserve failed
attempts and check both exit codes and records. Missing responses are not zeros.

## Workflow limits

- Judgment inspection has no supported accept/correct/reject action; unmatched and off-rubric findings remain provisional.
- Passing rubric status does not fully verify current-solution provenance. Keep source unchanged within a run; changed solutions need fresh identities.
- Historical answer-table score files may lack a full scoring profile; retain the report and chosen configuration with comparison snapshots. Text rubric results bind the judge and scorer versions and their exact rubric inputs.
- Re-scoring replaces development scores and the report. Snapshot before revision or accepted comparison. No automatic release-acceptance workflow exists.

## Viewer

```bash
.venv/bin/python tools/noharm.py view
```

Open [localhost:9000](http://localhost:9000/) and select the project. `--port 9001`
uses another port. The default-root order is in
[Agent execution](agent-skills.md#agent-execution). The viewer reads/reviews files;
stage buttons prepare agent prompts. Follow [STARTUP.md](../STARTUP.md) for verified links.

Missing bindings appear unverified; changed tasks hide stale scores and receive
no rank. Legacy `/noharm/runs/PROJECT/...` links require that project selected,
otherwise return 404. Trial controls appear only for multiple trials.

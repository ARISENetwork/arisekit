# Rubric implementation reference

Developer reference for rubric imports, validation, editor integration, and
compatibility with older projects. For setup and daily use, see the
[NOHARMKit guide](../README.md).

NOHARMKit supports the text rubric format beside the legacy answer-table
format. The source is `davidwumdphd/noharm-science`, main at
`6d803fee097fef0040a58e017053b2e88238ef60` (PR #1, 2026-10-25).
The source repository remains read-only. No pilot corpus was imported.

## Source

[`../upstream-text-v2.json`](../upstream-text-v2.json) records source hashes,
imported hashes, exact source commit, reference hashes and the adaptation patch.
The imported Python dependency closure is namespaced under
`tools/noharm_science/`. It retains the pinned validators and the scorer implementation.
Only namespace imports and profile paths change there.

The existing answer-table editor retains its 21-file source pin. The new
editor extracts the pinned v2 controls and Main approach/Add-ons sections.
Toolkit loading, save conflicts, history, timing and review provenance remain
local. This is the explicit integration exception to the older noharm-kit editor
ownership rule: the owner designated noharm-science as the current format and
editor source. Compact role headings remain visible, rating labels name Clinical
Appropriateness and Error Severity, and imported drafts say Unreviewed.

The toolkit host supplies only the project's judge/scorer source commit to the
editor and preview. Both select the same host validator as load/save, including
the current rules for current projects. Missing or legacy pins retain the original validation.
This host-specific wiring is included in the recorded adaptation patch; the
science repository, canonical validators, and vendored runtime are unchanged.

The host save-safeguard exception also exposes each editor's dirty, saving,
save-availability and error state through an optional local React context.
Save-and-continue awaits an explicit successful save result; a failed save keeps
the edits open. Save completion clears dirty state only for the revision sent;
newer edits remain unsaved and keep save-and-continue open. A separate in-flight
lock prevents overlapping saves even while editing continues. Page refresh is
deferred until the latest revision is saved, preserving the open editor.
The host owns Close, Escape and navigation confirmation, without
reading editor labels or classes. Standalone unload warnings and preview-only
save restrictions remain. Both integration patches record the callback wiring;
source repositories, rubric controls, validators and scientific behavior remain
unchanged. Saving still does not establish clinical acceptance.

Verify the import offline from the ARISEKit root:

```sh
scripts/dev/.venv/bin/python toolkits/noharmkit/tools/check_text_v2_upstream.py
```

## Portable expert review

Text rubric cases and mixed-format projects use the same self-contained HTML review
workflow as legacy answer tables. The existing text rubric editor exposes a storage
adapter; its server wrapper, clinical controls and validation remain intact.
Offline storage retains reviewer identity, editing history and current case.
Assignments carry only the project's judge/scorer source pin, and imports check
that pin against current project provenance before writing. Native text rubric hashes
bind source and reviewed records. Unknown ratings and unresolved notes remain
drafts, independently of successful review import. The storage adapter and
revision safeguards are recorded in the text rubric adaptation patch.

## Import

Create a project and import its supplied Task and Solution through the existing
workflow first. Then import a raw text rubric record or an envelope with `record`:

```sh
scripts/dev/.venv/bin/python toolkits/noharmkit/tools/noharm.py import-rubric \
  toolkits/noharmkit/projects/my-project --case Case001 --file /path/Case001.json --dry-run
scripts/dev/.venv/bin/python toolkits/noharmkit/tools/noharm.py import-rubric \
  toolkits/noharmkit/projects/my-project --case Case001 --file /path/Case001.json
```

The importer creates the next unused `runN` version and refuses overwrites.
It preserves the source bytes and their hash in a separate `.source.json` file.
The status receipt records imported authority and the tooling source commit.
No human review or clinical acceptance is inferred from import or saving.

The draft validator allows unknown ratings and unresolved notes with warnings.
Scoring requires resolved ratings. Severity floors remain warnings in both
validator modes, matching the source. Legacy counseling can be inspected, but the scorer
refuses it until rebuilt under the current rules.

## Execution

Imported scoring-valid v2 versions use the earlier judge for judging and the scorer for deterministic
scoring through the existing CLI and saved API setup. The earlier judge sees item text and IDs,
without omission rows, appropriateness, severity, tags or `addOn` ratings. The
existing model backend, credit authorization and checkpoint controls still apply.

the scorer reports omission, commission, error bounds and optimal status. It does not
produce F1. The app and report keep native scorer results separate from legacy F1,
including mixed-format projects and exports. Missing bindings, failed rubric
status, or changed rubric, task, response or judgment prevent old scores from
appearing current. Text rubric hashes use the pinned compact UTF-8 convention;
legacy hashes retain their original serialization.

## Authoring

New CLI and browser generation use text rubrics. Local agent guidance, contributor
and integrator prompts, validation repairs, and independent model ratings use
the pinned contract and authoring rules. Each new criterion has an omission row;
main approaches and `addOn: true` items carry explicit Clinical Appropriateness
and Error Severity ratings. Rating models assess C1 and every criterion item.
Severity floors are hard constraints for new model-authored drafts and ratings,
while imported or human-edited rubrics retain the pinned validator's warnings.

The new `generate-text-v2` and `rate-text-v2` skills are local prospective
adapters, not source-repository generation prompts. Exact contract and rules
copies are covered by the upstream manifest. Generation identities bind the
source commit, prompt, schema, rules, validator, route and reasoning settings.
One validation repair preserves the original draft and separate call receipt.
Generated output remains unreviewed and never implies clinical acceptance.

Native API generation sends a strict provider schema on initial drafts,
contributor and integrator calls, and bounded repairs, through both saved API
configuration versions and the CLI. Optional `addOn` is nullable only in the
provider schema; null fields are removed before canonical validation and storage.
Generated IDs use nonempty strings on the provider wire, avoiding identifier-regex
decoding loops. The canonical schema still enforces the original ID patterns,
and the validator checks numbering before a rubric can pass. Incomplete or
malformed JSON remains a failure, including output cut off at a provider limit.
Native earlier judge API calls also enforce their provider schema. OpenRouter routing requires
schema support. Local schema, clinical-rule and literal-evidence checks still run;
provider enforcement does not establish clinical coverage or correct mapping.

Item ratings share one schema definition across C1 and every item, preserving
the exact required IDs and rating constraints while avoiding repeated provider
grammar definitions. The canonical rubric format and the scorer remain unchanged.

The prospective generation coverage review asks for compatible complete
alternatives, broad add-ons, and the supportive-care criterion. The supplied
Solution anchors the draft without becoming an exhaustive whitelist. Evaluated
responses and prior judgments remain excluded from generation inputs.

Local earlier judge mapping guidance explicitly checks complete courses, safeguards and
current versus later-care timing against the whole response. Integrators recheck
disputed fields instead of combining incompatible contributor mappings. Equivalent
wording may match an existing item, but additional material advice and genuinely
uncovered actionable instructions remain visible as unmatched or off-rubric.
These are prompt clarifications beside the pinned earlier judge rules. The canonical schema,
validators and the scorer policy are unchanged; unresolved results remain valid outcomes.

Use `generate --format answer-table` for legacy authoring. The Python
`generate()` compatibility entrypoint and saved raw web jobs without a format
marker retain legacy behavior; new browser requests explicitly select text rubrics.
Native CLI advisory ratings and API rating teams support appropriateness and
severity. The optional RAND research-panel command remains legacy-only and
refuses native rubrics before calling a provider.

No historical rubrics, frozen studies, judgments or v34 corpus are converted.
Response collection remains one independent output per model/case/trial, with
no response integrator. Judging and scoring follow the saved rubric's format.

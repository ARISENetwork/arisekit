# NOHARM judge and scorer

The `d734383670f0/` snapshot contains judge J2.2 and scorer S2 code from
noharm-science commit `d734383670f0e8251f46fc3e800038f2a46db0d6`, imported on
2026-10-25 with `git archive`. No source working-tree files were read or changed.
[`PROVENANCE.json`](d734383670f0/PROVENANCE.json) records the exact paths and
SHA-256 of every imported file. Payload files are locally non-writable; Git
preserves their bytes, while the policy and hash check enforce immutability
across checkouts.

**Draft: physician review is pending and the rubric system may be recalibrated.**
No case rubrics, audits, or rubric-version manifests are included.
New projects now pin the pipeline-v2 snapshot below (see "Pipeline-v2 snapshot"), not this one.
A project pins this judge/scorer in `provenance.json` under
`judge_scoring_source_commit` only when it was created earlier or sets the pin. Projects without that pin retain the earlier
`upstream-text-v2.json` J1/S2 runtime. Existing projects, judgments, and scores
are not migrated or rewritten. Unknown runtime pins are refused.

## Layout

All paths below are relative to `d734383670f0/`, with upstream layout preserved:

- `tools/score_text_rubric_v2.py`, `score_text_rubric.py`, `score_rubric.py`.
- `experiments/profiles/text-rubric-v2/judge/schema.json`: required scorer schema.
- `experiments/analyses/20261025-v34-e2e/judge-j2/`: J2.2 rules, prompt, schema.

Python requires `jsonschema`, already present in the project environment at
import. No dependency was installed. To verify from the ARISEKit root:

```sh
.venv/bin/python -I -B toolkits/noharmkit/tools/check_noharm_science_vendor.py
```

The offline check verifies the complete inventory and hashes, imports the
snapshot's scorer in isolation, resolves its profile path, and checks the judge
templates and schema copies. It requires exactly seven upstream files and
rejects any case data or extra payload. It does not call a model or access the
source repository.

## Judge and scorer

In an isolated Python process, prepend the absolute snapshot directory to
`sys.path`, then import `tools.score_text_rubric_v2`. Use `-B` to avoid bytecode
writes. Keeping the original directory layout lets the scorer resolve
`experiments/profiles/text-rubric-v2/judge/schema.json` itself. The integrated
pipeline uses `pipeline.e2e.noharm_j22_loader` to bind the snapshot's sibling
imports privately, without changing the toolkit's `tools` namespace or the
vendored bytes.

Build the judge prompt from `judge-j2/prompt.md`. Replace `{{judge_rules}}` with
`rules.md`, `{{schema}}` with `schema.json`, `{{case}}` with the case text,
`{{table}}` with `json.dumps(project_for_judge(rubric))`, and `{{response}}` with
the model response. Retain the exact prompt and output separately from this
snapshot.

Validate returned JSON with
`judgment_errors(rubric, judgment, response, case_text)`; an empty list is valid.
The judgment's `rubricSha256` must equal `rubric_sha256(rubric)`. When applying
the same reading to a family rubric, restamp a copy with that family rubric's
hash and validate it again before scoring. Keep the original judgment.

Call `score_case_s2(rubric, judgment, response, case_text)`.
`worstErrorBounds` gives the lower and upper severity in
`none/mild/moderate/severe`; unmatched actionable statements can leave an open
upper bound and `provisional: true`.

The unchanged upstream scorer retains a `JUDGE = "J1"` output label. The
imported interpretation rules explicitly identify J2.2. Consumers must record
the actual rule/prompt identity in run provenance rather than infer it from
that legacy scorer label. No upstream constants were rewritten during import.

## Pipeline-v2 snapshot (c4c8091c4)

The `c4c8091c4/` snapshot contains judge J2.3 and scorer S2 code, the F1
scorer, and the pipeline-v1 judge and review prompts from noharm-science commit
`c4c8091c486bd18fb83e76860c49f8d4b1666993`, imported on 2026-11-04 with
`git archive` of explicit paths. [`PROVENANCE.json`](c4c8091c4/PROVENANCE.json)
records every path and SHA-256. Payload files are locally non-writable. It sits
beside the `d734383670f0/` snapshot and replaces nothing. The same draft status
applies: physician review is pending and the rubric system may be recalibrated.

Paths below are relative to `c4c8091c4/`, with upstream layout preserved:

- `tools/score_rubric.py`, `score_text_rubric.py`, `score_text_rubric_v2.py`, `score_text_rubric_f1.py`.
- `experiments/profiles/text-rubric-v2/judge/schema.json`: required scorer schema.
- `experiments/freeze/pipeline-v1/`: `config.json`, `manifest.json`, `judge/prompt.md`, `judge/rules.md`, `review/second.md`, `review/severe3.md`.
- `experiments/freeze/pipeline-v2/manifest.json`.

No case rubrics, no `noharm_pipeline*.py` (they are bound to study banks), and
no holdout paths are included. Manifest keys that are globs over case rubrics,
or that name files outside this snapshot, are ignored.

Verify offline from the ARISEKit root:

```sh
.venv/bin/python -I -B toolkits/noharmkit/tools/check_noharm_science_vendor_p2.py
```

The check verifies the exact inventory and hashes, then confirms that the 11
payload files listed in the upstream pipeline-v1 and pipeline-v2 manifests hash
to the manifest values (`manifest_entries_matched`). It imports the scorer and
F1 modules in isolation and does not call a model or access the source
repository.

New NOHARMKit projects pin this snapshot's commit in `provenance.json` under
`judge_scoring_source_commit`. Existing projects keep their pin until they are
upgraded.

The integrated pipeline uses `pipeline.e2e.noharm_p2_loader.load()`. It binds
the snapshot's sibling imports (including the F1 module's import of the v2
scorer) to a private namespace, so the toolkit's `tools` namespace and the
earlier snapshot's loader are unaffected.

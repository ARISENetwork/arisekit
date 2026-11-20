---
name: arisekit/implementation-plan
description: Synthesizes upstream artifacts into an implementation plan and build specification. The build specification is not runnable; build/scaffold must emit `runnable-benchmark.json` before run configuration.
---

# Implementation plan

You are the terminal stage of the plan-only chain in the ARISEKit
benchmark pipeline (CUJ 01). Take every upstream artifact (need
statement, existing-coverage, compliance scope, data profile,
rubric, study plan) and synthesize them into a human-readable
`implementation-plan.md` plus a versioned
`benchmark-build-spec.json`. A deterministic scaffold command can
consume the sidecar without reinterpreting clinical decisions from
prose. After build/scaffold, a separate runnable manifest bridges this
plan to the runner. After a run, universal inspection is automatic;
`arisekit/release-writeup` is an optional publication path.

The [text example](../../examples/p0-golden-path/README.md) includes a complete scaffold handoff.
The plan and sidecar must be specific enough that the deterministic
scaffold command can build supported cases without guessing and a
coding agent can see exactly why an unsupported case is blocked.

## Recognize existing MAST benchmarks

Read the [MAST recognition reference](../existing-benchmark-search/catalog/mast-benchmarks.md) before responding to a named
benchmark. Use its aliases and task patterns from the first turn. Carry the
chosen family and requested adaptation forward; clarify a changed family
without asking the user to define known acronyms.

## What you produce

For source-grounded image tasks, use the dedicated
[medical image generation workflow](../../examples/medical-images/README.md).
Its executable finite-answer profiles are classification and closed-answer VQA;
compatible profiles may share the source store and vision delivery. Record any
report, spatial, open-answer, volume or DICOM adapter gap explicitly. Do not
route an image request into the FHIR/text generator or substitute a report judge
for classification scoring. Keep the assisted confirmations in this skill
separate from the frozen autonomous image-generation arm.

Produce two files:

1. `implementation-plan.md`, using
   [`templates/implementation-plan.template.md`](templates/implementation-plan.template.md).
   This is the reviewable rationale and implementation handoff.
2. `benchmark-build-spec.json`, using the exact versioned contract
   below. This is a lossless transcription of confirmed build
   decisions, artifact hashes, and blockers. It is not a second place
   to make clinical decisions.

Neither file is a runnable benchmark. The build-to-run contract is:

`implementation-plan -> build/scaffold -> runnable-benchmark.json -> run-config`

The scaffold must emit `runnable-benchmark.json` with the entry
point, dataset and scorer digests, required assets, environment,
source revision, smoke-test result, and readiness state. Builder
drafts require this manifest. A curated roster benchmark may create
the same schema through `build_manifest_for_directory()`.

The plan must capture:

- **Benchmark identity.** Name, slug (kebab-case), version,
  1-paragraph description, and modality.
- **MAST compatibility.** Confirmation that the plan produces a
  submodule-compatible benchmark, with the MAST category it maps
  to if known.
- **Dataset loader spec.** Which ARISEKit `Dataset` method to use
  (`from_jsonl`, `from_csv`, `from_hf`, or a custom subclass).
  Exact field mapping: source field -> `BenchmarkItem` slot
  (`prompt`, `ground_truth`, `metadata`, `attachments`).
- **Data-governance gate.** The source classification, intended
  release posture, and a separate verbatim authorization to
  materialize normalized case rows. Do not infer this authorization
  from a rights basis, compliance review, or plan confirmation.
- **Scorer spec.** Which ARISEKit primitive(s) to compose. Verbatim
  judge prompts, concordance formulas, pass/fail predicates.
  Sub-score (category) breakdown.
- **Runner configuration.** Expected item count, trial count for
  CIs, parallelism, retry/budget guardrails (with pointers to the
  framework defaults, not a reimplementation).
- **Model list for first run.** Which model(s) the author wants in
  the initial sweep, tied back to the compliance scope's provider
  compatibility.
- **Output layout.** Standard ARISEKit paths
  (`results/raw/<benchmark>/<model>.jsonl`,
  `results/scores/<benchmark>/<model>.csv`, compiled CSV shape).
- **Rater tooling handoff.** How the study plan's rater workflow
  is fed into the benchmark (pre-scored items, judge prompts, or
  pending rater-UI).
- **Library and scaffold-adapter gaps.** Any ARISEKit primitive the
  plan needs that does not exist, or any existing primitive that the
  versioned scaffold contract cannot bind. Each gap becomes an issue
  CUJ 02 must surface before proceeding.
- **Open questions.** Anything upstream skills left unresolved.
- **Acceptance checklist.** The specific conditions that mark the
  benchmark as ready: smoke run passes on N items, concordance
  threshold met on the calibration set, output layout matches
  MAST, etc.
- **NOHARM-style blueprint and export contract, when selected.**
  Map the upstream decisions to
  `arisekit.authoring.blueprint.BenchmarkBlueprint`, the generated-bundle
  exporter in `benchmarks.noharm_reference`, immutable
  `arisekit.run_manifest.RunManifest` records, and a three-family
  synthetic fixture.
- **Multimodal image-attachment binding, when selected.** Record every local
  PNG/JPEG path, digest, byte size, media type, case order, and the user's
  explicit authorization to copy the image bytes. Keep semantic image-report
  judging separate from the deterministic structural scorer.

## Machine-readable build sidecar

Select the schema from the supported authoring pattern. Use
`arisekit.benchmark-build-spec.v1` for text benchmarks and
`arisekit.benchmark-build-spec.v2` only for the Agentic/FHIR contract below.
Use `arisekit.benchmark-build-spec.v3` only for the multimodal image-attachment
contract below. Do not mix version-specific fields or relabel an agentic or
multimodal benchmark as text.

Version 1 can deterministically scaffold only:

- a local top-level-object JSONL or headered CSV source; and
- one auto-bindable scorer kind: `exact-match`, `contains`, `choice`,
  or `numeric`; the explicit `rubric-judge` adapter additionally binds
  `arisekit.rubric-judge.v1` for public/synthetic packages.

Do not broaden this list by analogy. `regex_match`, composed scorers,
unbound LLM judges, concordance scorers, agentic scorers, multimodal adapters,
NOHARM exporters, and custom subclasses require a named scaffold
adapter that version 1 does not have. Record the exact primitive as a
blocking library or scaffold-adapter gap and set readiness to
`blocked`; do not substitute a simpler scorer or generate placeholder
Python.

Write this exact top-level shape:

```json
{
  "schema_version": "arisekit.benchmark-build-spec.v1",
  "benchmark": {
    "name": "ED triage acuity",
    "slug": "ed-triage-acuity",
    "version": "0.1.0",
    "description": "User-confirmed benchmark description.",
    "modality": "text",
    "mast_category": "diagnostic",
    "mast_compatible": true
  },
  "source": {
    "kind": "jsonl",
    "path": "data/source.jsonl",
    "sha256": "<64 lowercase hexadecimal characters>",
    "field_map": {
      "id": "case_id",
      "prompt": "vignette",
      "ground_truth": "label",
      "metadata": {
        "specialty": "service",
        "severity": "acuity"
      },
      "attachments": null
    },
    "system_prompt": {
      "text": "Exact prompt text.",
      "sha256": "<SHA-256 of the UTF-8 prompt bytes>"
    }
  },
  "data_governance": {
    "classification": "deidentified",
    "release_posture": "restricted",
    "materialization_authorization": {
      "authorized": true,
      "actor": "authorizing user name or role",
      "confirmed_at": "2026-07-27T12:00:00Z",
      "text": "Verbatim authorization to materialize normalized case rows."
    }
  },
  "scorer": {
    "kind": "choice",
    "primitive": "arisekit.scorer.choice",
    "options": {
      "choices": ["1", "2", "3", "4", "5"],
      "case_sensitive": false,
      "name": "accuracy"
    }
  },
  "runner": {
    "trials": 3,
    "threads": 4,
    "max_retries": 3,
    "retry_backoff": 1.5,
    "temperature": 0.0,
    "max_tokens": 512,
    "max_cost": 25.0,
    "max_cost_per_call": 0.25,
    "require_known_cost": true,
    "max_calls": 3000
  },
  "smoke_test": {
    "model": "provider/model-snapshot",
    "limit": 10,
    "trials": 1
  },
  "first_sweep": [
    {
      "model": "provider/model-snapshot",
      "provider": "provider",
      "trials": 3
    }
  ],
  "artifacts": [
    {
      "role": "need-statement",
      "path": "need-statement.md",
      "sha256": "<SHA-256 of the exact file bytes>"
    },
    {
      "role": "existing-coverage",
      "path": "existing-coverage.md",
      "sha256": "<SHA-256 of the exact file bytes>"
    },
    {
      "role": "compliance-scope",
      "path": "compliance-scope.md",
      "sha256": "<SHA-256 of the exact file bytes>"
    },
    {
      "role": "data-profile",
      "path": "data-profile.md",
      "sha256": "<SHA-256 of the exact file bytes>"
    },
    {
      "role": "rubric",
      "path": "rubric.md",
      "sha256": "<SHA-256 of the exact file bytes>"
    },
    {
      "role": "study-plan",
      "path": "study-plan.md",
      "sha256": "<SHA-256 of the exact file bytes>"
    },
    {
      "role": "implementation-plan",
      "path": "implementation-plan.md",
      "sha256": "<SHA-256 of the exact file bytes>"
    }
  ],
  "readiness": {
    "status": "ready",
    "data_profile": "materialized",
    "allowed_model_routes": ["provider/model-snapshot"],
    "library_gaps": [],
    "open_questions": [],
    "user_confirmation": {
      "actor": "user name or role",
      "confirmed_at": "2026-07-27T12:00:00Z",
      "text": "Verbatim confirmation."
    }
  }
}
```

Contract rules:

- Paths are relative to the sidecar. Hash the exact bytes on disk;
  never invent or approximate a digest.
- The `benchmark` object has exactly `name`, `slug`, `version`,
  `description`, `modality`, `mast_category`, and `mast_compatible`.
  `modality` is distinct from `mast_category` and becomes the package
  manifest's modality. A ready version-1 sidecar requires exactly
  `"text"`. A blocked sidecar preserves another requested modality
  verbatim and names the missing adapter; do not relabel multimodal or
  agentic content as text.
- A ready sidecar has `source.kind` equal to `jsonl` or `csv`.
  Field-map values name top-level JSON object keys or CSV headers. A
  blocked sidecar preserves another requested source kind verbatim so
  the missing adapter is reviewable. `field_map.attachments` must be
  `null` for a ready version-1 sidecar: the scaffold does not copy,
  hash, or safely rebase attachment files. Any attachment mapping or
  multimodal item sets readiness to `blocked` with a named source-
  adapter gap. Use `null` for an absent `system_prompt`.
- Metadata maps output metadata keys to source headers. Do not silently
  place every unused source field in metadata.
- `data_governance.classification` is exactly one of `public`,
  `synthetic`, `deidentified`, `limited`, or `identifiable`.
  `release_posture` is exactly one of `public`, `restricted`,
  `private`, or `held-out`. A ready version-1 sidecar rejects
  `limited` and `identifiable` data. A `public` release posture is
  valid only for `public` or `synthetic` data.
- Materializing `package/cases.jsonl` is a distinct data-handling
  action. A ready sidecar requires `materialization_authorization`
  with `authorized: true`, a named actor, an RFC 3339 timestamp, and
  their exact authorization text. Do not treat plan confirmation,
  de-identification, a source-rights statement, or an allowed model
  route as this authorization. A refusal uses `authorized: false`
  with the actor, timestamp, and verbatim text and keeps the sidecar
  blocked. These three refusal-audit fields cannot be `null`, even
  when another blocker already keeps the sidecar blocked.
- A ready sidecar has scorer `kind` equal to `exact-match`,
  `contains`, `choice`, `numeric`, or the explicit `rubric-judge` adapter,
  and `options` must be accepted
  keyword arguments for the named primitive. A blocked sidecar
  preserves the requested scorer kind and exact primitive verbatim and
  adds the adapter gap. Do not include secrets or provider credentials.
- Use these canonical, case-sensitive `library_gaps[].primitive`
  names for unsupported version-1 adapters. Append the exact sidecar
  value without normalization: an unsupported `source.kind` uses
  `arisekit.scaffold.source-adapter.<source.kind>`; an unsupported
  `benchmark.modality` uses
  `arisekit.scaffold.modality-adapter.<benchmark.modality>`; and a
  non-null attachment field uses
  `arisekit.scaffold.attachment-adapter.<field_map.attachments>`.
  An unsupported scorer uses the exact requested `scorer.primitive`,
  with no prefix or substitution. Record every applicable gap; an
  unrelated gap does not satisfy one of these adapter blockers.
- The seven artifact roles above are required exactly once. Their
  hashes bind the sidecar to the reviewed decisions and let the
  scaffold command reject stale inputs.
- `readiness.status` is `ready` only when the data profile is
  `materialized`, the source path and digest exist, every open question
  is resolved, `library_gaps` is empty, the smoke-test route appears in
  `allowed_model_routes`, and the set of `first_sweep[].model` values
  equals `allowed_model_routes`. Each first-sweep row supplies the
  provider for that runtime route. The user confirmation and the
  data-governance gates above must also be present and valid.
- `readiness.allowed_model_routes` is the reviewed plan's execution
  allowlist. It is not authorization to disclose case rows to a model
  provider. Every non-public generated version-1 package requires
  `arisekit.egress.ProviderDisclosureAuthorization` at runtime, bound
  to the SHA-256 of the exact generated
  `package/asset-manifest.json` bytes, the release posture, and the
  selected route's provider. Deterministic version-1 scorers use
  `judge_providers: []`. Do not put that object in the build sidecar:
  its `generated_bundle_hash` does not exist until scaffolding
  succeeds, and scaffolding performs no inference. It is an externally
  supplied, auditable approval assertion, not a verified signature;
  trust depends on the workflow and controls that issue its file.
- For provisional data or an unsupported scorer, still emit the
  sidecar, but use `null` for unavailable source values, set status to
  `blocked`, and add a precise blocking entry such as:
  `{"primitive":"arisekit.judges.MultiJudgePanel","reason":"benchmark-build-spec.v1 has no deterministic scaffold adapter","owner_or_issue":"unassigned"}`.
- A ready sidecar authorizes deterministic local scaffolding only. It
  does not authorize a paid run, certify privacy or rights, approve
  clinical content, authorize publication or sharing, or admit the
  result to MAST. For every non-public release posture, the scaffold
  must add a root `.gitignore` entry for `package/cases.jsonl` and a
  prominent README warning. Package provenance records the
  classification, release posture, authorization actor and timestamp,
  and SHA-256 of the exact authorization text, not that text itself.

### Agentic/FHIR version-2 differential

Version 2 is a narrow extension for the implemented CUJ 08 path. Start with
the version-1 top-level shape and common artifact, runner, smoke-test,
first-sweep, readiness, confirmation, path, and hash rules. Change or add only
the fields below:

- Set `schema_version` to `arisekit.benchmark-build-spec.v2` and
  `benchmark.modality` to `agentic-fhir`.
- Use a local top-level-object JSONL source. Version 2 does not accept CSV,
  remote FHIR servers, nested sources, or multiple Bundles per case.
- Add `source.field_map.fhir_bundle` with the literal value `fhir_bundle`.
  Keep `source.field_map.attachments` null. The `id`, `prompt`, and
  `ground_truth` mappings remain required.
- Add this exact `agentic` object, replacing the example allowlist and turn
  limit only with reviewed values:

  ```json
  {
    "environment": {
      "kind": "fhir-r4-in-memory",
      "primitive": "arisekit.env.fhir.FHIREnvironment",
      "fhir_version": "R4",
      "isolation": "per-item-trial"
    },
    "tool_catalog": "arisekit.fhir-tools.v1",
    "allowed_tools": ["get_patient"],
    "max_turns": 3
  }
  ```

  `allowed_tools` is a non-empty, duplicate-free, ordered subset of the named
  catalog. `max_turns` is a positive integer. Do not embed custom schemas,
  executable tool code, provider credentials, or a remote environment.
- For deterministic pass@1, use this exact scorer binding. A reviewed
  generic rubric may instead select the versioned `rubric-judge` adapter:

  ```json
  {
    "kind": "pass-at-one",
    "primitive": "arisekit.agentic.PassAtOneScorer",
    "options": {
      "name": "pass_at_1",
      "condition_schema": "arisekit.agentic-pass-condition.v1"
    }
  }
  ```

- Map each row's ground truth to an object with this exact shape:

  ```json
  {
    "schema_version": "arisekit.agentic-pass-condition.v1",
    "required_tool_calls": [
      {
        "name": "get_patient",
        "arguments": {"patient_id": "p1"}
      }
    ],
    "final_response_contains": ["Hernandez"]
  }
  ```

  Both arrays are non-empty and duplicate-free. Required call names must be
  allowlisted, and arguments must match the selected catalog schema exactly.
  Pass@1 uses AND semantics: every required call must succeed with the exact
  JSON arguments, and the final response must contain every required
  substring using case-insensitive matching.
- Each source row contains exactly one FHIR R4 Bundle in the literal
  `fhir_bundle` field. The mapped item id must be a valid FHIR id and must
  equal the Bundle `id`. The Bundle has `resourceType: "Bundle"`, a non-empty
  `type`, and resource objects in every entry. Scaffolding removes the Bundle
  from normalized `cases.jsonl`, writes it to
  `package/cohort/<item-id>.fhir.json`, and binds it through `package/env.json`.
- A ready version-2 sidecar requires classification `public` or `synthetic`
  and release posture `public`, plus the normal explicit materialization
  authorization. The initial adapter has no non-public version-2 path. Keep a
  sidecar blocked when these exact governance gates are not met.
- If a draft has no local source selection, preserve the v2 intent but
  leave the source path and digest unresolved, record the local-source open
  question, preserve any independently identified adapter gaps, and keep
  readiness `blocked`. Never invent FHIR rows, source paths, or hashes.

The scaffold materializes the full schemas for the selected catalog tools,
one case-to-cohort binding per item, the fixed environment, isolation scope,
and maximum turns in `package/env.json`. `Benchmark.from_package` binds the
same environment and `PassAtOneScorer`; each item and trial gets a fresh
environment. LLM trajectory judging, custom tool catalogs, remote FHIR
servers, richer action-state predicates, and multimodal attachments remain
unsupported within version 2. Record them as gaps instead of substituting
pass@1; use the exact version-3 contract below for its narrow image path.

### Multimodal image-attachment version-3 differential

Version 3 is a narrow extension for CUJ 09 attachment transport. Start with
the version-1 top-level shape and common artifact, runner, smoke-test,
first-sweep, readiness, confirmation, path, and hash rules. Change or add only
the fields below:

- Set `schema_version` to `arisekit.benchmark-build-spec.v3` and
  `benchmark.modality` to `multimodal`.
- Use a local top-level-object JSONL source. Version 3 does not accept CSV,
  remote files, nested records, DICOM, or non-image attachments.
- Set `source.field_map.attachments` to the literal value `attachments`. Do not
  include `fhir_bundle` or `agentic`. The `id`, `prompt`, and `ground_truth`
  mappings remain required.
- Add this exact `multimodal` shape, replacing the example asset values only
  with values derived from the reviewed local files:

  ```json
  {
    "schema_version": "arisekit.image-attachments.v1",
    "assets": [
      {
        "path": "attachments/case-001.png",
        "sha256": "<64 lowercase hexadecimal characters>",
        "size_bytes": 1234,
        "media_type": "image/png"
      }
    ]
  }
  ```

  The object has exactly `schema_version` and `assets`. Every asset object has
  exactly `path`, `sha256`, `size_bytes`, and `media_type`. `assets` is
  non-empty and lexicographically ordered by path. Each path is a unique,
  case-insensitively unique, flat `attachments/<name>.png`, `.jpg`, or `.jpeg`
  path resolved from the build sidecar directory. A path cannot be absolute,
  remote, a data URI, contain traversal, or resolve through a symlink.
  `sha256` and `size_bytes` bind the exact regular-file bytes. `size_bytes` is
  between 1 byte and 10 MiB, and the full inventory is at most 100 MiB.
  `media_type` is exactly `image/png` or `image/jpeg`, and it must agree with
  the filename and image signature.
- Each source row's literal `attachments` value is a non-empty, duplicate-free,
  ordered list of one to four strings. Every string equals one inventoried
  asset path. Every inventoried asset is referenced by at least one row. Do not
  discover extra directory files or place unused assets in the package.
- Use this exact deterministic scorer binding for a ready initial v3 sidecar:

  ```json
  {
    "kind": "exact-match",
    "primitive": "arisekit.scorer.exact_match",
    "options": {
      "case_sensitive": false,
      "strip": true,
      "name": "accuracy"
    }
  }
  ```

  This scorer lets `stub/reference` prove image resolution, message encoding,
  checkpoint, scoring, and result plumbing. It does not measure semantic
  image-report quality and must not be described as GREEN. If the accepted
  rubric selects generic semantic judging, use `rubric-judge` with
  `options.rubric` in `arisekit.rubric-judge.v1`. GREEN and other specific
  unsupported primitives remain explicit library gaps. Do not substitute
  exact-match or a generic rubric for those requested scorers.
- A ready version-3 sidecar requires classification `public` or `synthetic` and
  release posture `public`. The normal verbatim
  `materialization_authorization.text` must explicitly authorize both writing
  normalized case rows and copying the inventoried image bytes into the
  generated package. Rights statements, plan confirmation, or authorization
  to write rows alone do not authorize the image copy.
- Every ready model route, including the planned smoke route, must be reviewed
  for image input. This is an execution compatibility decision, not a claim
  that ARISEKit certifies provider behavior.
- If a draft lacks the local JSONL or any referenced image, preserve the
  v3 intent, leave unavailable paths, digests, sizes, or media types unresolved,
  name every local-file question or adapter gap, and keep readiness `blocked`.
  Never invent, upload, or silently omit image bytes to make the sidecar ready.

Scaffolding verifies the source and image bytes before writing, copies each
asset once to flat `package/attachments/<basename>`, writes every normalized
case with ordered package-relative paths, records the asset declarations and
case bindings in `package/attachments.json`, and includes all images in
`package/asset-manifest.json`. Package loading verifies and resolves those paths
inside the package. The model client must fail on a missing, changed, or
unsupported attachment instead of silently skipping it. The keyless reference
stub exercises the same attachment-resolution and encoding path, and a smoke
pass establishes structural execution readiness only.

Semantic image-report judging, GREEN compatibility, DICOM, remote or non-image
attachments, non-public image packages, nested package paths, transformations,
and a general media pipeline remain unsupported adapters. Record them as gaps
instead of broadening version 3 by analogy.

## How to run the conversation

1. Read every upstream artifact. Confirm each is present. If any
   is missing, route the user back to the relevant skill rather
   than filling in gaps.
2. Walk the user through the plan section by section. Do not
   paraphrase the upstream artifacts into vague prose; quote them
   and let the plan be concrete.
3. At every section, ask: "Is this specific enough for a coding
   agent to build without guessing?" If not, push for more
   specificity.
4. Call out library gaps explicitly. A plan that depends on a
   primitive we do not ship yet is a plan that will stall at
   implementation time; better to see the stall now.
5. If `rubric.md` chose NOHARM-style, complete the conditional
   contract below. Inspect the repository before naming an export
   or campaign API; if it is absent, record an adapter gap instead
   of inventing a name.
6. Read the compliance scope's classification and release decision
   back to the user. Separately ask whether they authorize the local
   scaffold command to materialize normalized rows in
   `package/cases.jsonl`. Record the answer, actor, and timestamp
   verbatim. Do not convert silence or general plan approval into
   authorization.
7. Read the plan back to the user end to end. Ask them to confirm
   it matches the benchmark they intended to build. Record their
   confirmation verbatim.
8. Write `implementation-plan.md`, then hash it and every upstream
   artifact and write `benchmark-build-spec.json`. Validate that the
   sidecar repeats the accepted decisions without adding new ones.
9. For a ready version-1 sidecar, remind the user that CUJ 02 runs
   `arisekit new-benchmark --spec benchmark-build-spec.json`, followed
   by `arisekit check-benchmark <slug>`. Explain that a non-public
   generated package requires provider-disclosure authorization, which
   is created only after the package hash exists and before the first
   inference run. Explain that runtime checks the assertion's bindings,
   not a cryptographic signature, so the issuing workflow establishes
   trust. For a blocked sidecar, name every gap and do not claim it can
   scaffold.
10. For a ready Agentic/FHIR version-2 sidecar, give the same scaffold and
    check commands, then name the exact planned tool-capable smoke route. Make
    clear that the initial adapter accepts only public or synthetic data with
    a public release posture and that the smoke pass proves structural
    execution readiness, not clinical quality.
11. For a ready multimodal version-3 sidecar, give the same scaffold and check
    commands, confirm that every local image byte is inventoried and explicitly
    authorized for copying, and name the exact image-capable smoke route. Make
    clear that exact-match and `stub/reference` prove attachment transport only;
    semantic image-report scoring remains a separate adapter and scorer-
    iteration milestone.

## NOHARM-style implementation contract (conditional)

1. Set the blueprint schema to
   `arisekit.benchmark-blueprint.v2`; pin its benchmark version,
   specialty, response, judge, aggregation, sources, case families,
   and review events. Set `strict_noharm_topology: true` and
   `expected_variants_per_base: 10`.
2. Map the data-profile ledger into `SourceRecord` fields, including
   the explicit release scope and authorization hash, authorizer, and
   timestamp. Carry
   source ids into every supported base presentation, reference
   recommendation, rubric action, guidance, and invariance
   attestation. Rights assertions remain recorded claims, not
   certification. Export remains blocked if rights are unknown, the
   release record is incomplete, or the requested access classification
   exceeds the authorized scope.
3. Require every real case-family workflow to be complete before
   export: named clinical locks, exactly ten variants named
   `<base>-0` through `<base>-9`, invariance attestations, and
   locked guidance. Use exporter-compatible family ids (letters
   followed by three digits) and canonical positive-integer rubric
   option ids for the generated NOHARM bundle.
4. Render the frozen `ResponseContract` into the exact response
   prompt bytes and pin those bytes with the judge assets in
   `PinnedNoHarmAssets`. Record the reviewed reference dependency-manifest
   inventory as its approved `runtime_dependency_lock_sha256`, and put
   that same declaration in the blueprint `JudgeContract`; do not copy
   private dependency-file content into the generated bundle. Add a strict
   `GenerationLineage` with the provider, requested and returned model
   identities, model family, response ids, generation manifest/code/input
   hashes, and timestamp. Record identifiers and hashes only, not private
   generation inputs. Then use
   `export_noharm_bundle` with an explicit access classification and
   expected base-case count.
   Validate the result with
   `NoHarmCompatibleBundle`. The fixed 30-case
   `NoHarmReferenceBundle` remains the validator for the public
   release only. Do not copy its `open: true` declaration onto
   generated data; generated metadata carries the explicit access
   classification and authored source-rights record.
5. Define one `RunManifest` per arm-model cell, including all
   content, prompt, rubric, guidance, judge, and code hashes;
   provider/model snapshot and config; trials, seeds, selection,
   and source revision. Bind the declared runtime dependency lock into
   the judge runtime hash and model configuration.
6. Build the three-family synthetic smoke fixture first. It must
   round-trip the blueprint, export 33 rows, and load through the
   compatible-bundle adapter. Its pass is structural, not clinical
   validation.

## Do

- Be specific. Library paths, class names, field names.
- Cite upstream artifacts by file name so the coding agent can
  traverse the chain.
- Name the MAST submodule compatibility contract explicitly:
  directory layout, `build()` factory, supported scorer binding, output
  CSV shape.
- For a NOHARM-compatible bundle, name the real exporter and
  validator separately from `arisekit.package.write_package`.
  The generic package writer can preserve `blueprint.json`, but it
  does not render the canonical NOHARM directory contract.
- Record the user's confirmation at the bottom of the plan. This
  is the artifact reviewers (and the user themselves, weeks
  later) come back to.
- Preserve the distinction between a human decision and a mechanical
  transcription. The sidecar may encode only choices already accepted
  in the upstream artifacts and implementation plan.

## Do not

- Do not invent ARISEKit primitives. If the needed primitive is
  not in the library today, flag it as a gap; do not pretend it
  exists.
- Do not re-open clinical decisions at this stage. If the user
  wants to change the rubric, send them back to
  `arisekit/rubric-design` rather than patching the plan in place.
- Do not skip the acceptance checklist. Without it, the coding
  agent has no way to decide when the benchmark is done.
- Do not write code. This stage produces a plan, not an
  implementation.
- Do not parse the final Markdown back into a build spec or ask the
  downstream coding agent to infer a field mapping. Write the sidecar
  directly from the same confirmed decisions used to write the plan.
- Do not mark an unsupported primitive as ready, emit placeholder
  scorer code, or approximate it with a supported built-in scorer.
- Do not infer materialization authorization from a classification,
  de-identification claim, rights basis, compliance approval, plan
  confirmation, or intended release posture.
- Do not describe `allowed_model_routes` as provider-disclosure
  authorization or pre-build a `ProviderDisclosureAuthorization` with
  a guessed package hash.
- Do not claim that blueprint completion, compatible-bundle
  validation, or a synthetic smoke pass certifies clinical
  quality, data authorization, privacy, or MAST admission.

## Exit

Write `implementation-plan.md` and `benchmark-build-spec.json`. Tell
the user:

1. Where both files live and whether the sidecar is `ready` or
   `blocked`.
2. If ready, that CUJ 02 starts with
   `arisekit new-benchmark --spec benchmark-build-spec.json` and then
   `arisekit check-benchmark <slug>`. The scaffold writes
   `runnable-benchmark.json` in `awaiting_smoke_test` state; the exact
   authorized smoke run records its result bundle and advances the
   manifest to `ready` or `blocked`.
3. If blocked, that the scaffold command will refuse to write a
   partial benchmark until the recorded gaps are closed.

## Upstream artifacts

- `need-statement.md` (required)
- `existing-coverage.md` (required)
- `compliance-scope.md` (required)
- `data-profile.md` (required)
- `rubric.md` (required)
- `study-plan.md` (required)

## Downstream readers

- The deterministic scaffold command in CUJ 02 consumes the build
  sidecar; a coding agent handles only explicitly unsupported work.
- `arisekit/run-config` consumes the runnable manifest produced by
  build/scaffold, never the implementation plan as proof of
  executability.
- MAST reviewers read this plan when evaluating the benchmark for
  graduation.
- Future maintainers (including the user, months later) read this
  plan to understand why the benchmark is shaped the way it is.

## Versioned judge and provider handoff

For `rubric-judge`, use primitive `arisekit.judges.rubric.RubricJudge` and
`options.rubric` with `arisekit.rubric-judge.v1`. Preserve the author's
criteria, positive weights, zero/one anchors, example scores and rationales,
pinned `arisekit.provider-profile.v1` judge settings, and separate judge
`max_calls`, `max_cost`, and `max_cost_per_call`. See
`examples/provider-profiles/rubric-example.json`. This is an explicit additive
scaffold adapter for public/synthetic text, FHIR, and image packages. Stub
smokes skip paid judges and produce no rubric score. Do not list this adapter
as a library gap when its complete versioned configuration is present.

For agentic paid runs, a total dollar budget needs a reviewed per-turn
reservation bound. The runner enforces calls and reservations before each
dispatch; it retains unknown costs and exposes a stop reason. Record the
chosen provider profile and the synthetic connection-check receipt separately
from the benchmark's clinical content.

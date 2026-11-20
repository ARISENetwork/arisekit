# Implementation plan

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/implementation-plan`
_Upstream:_ [`need-statement.md`](need-statement.md),
[`existing-coverage.md`](existing-coverage.md),
[`compliance-scope.md`](compliance-scope.md),
[`data-profile.md`](data-profile.md),
[`rubric.md`](rubric.md),
[`study-plan.md`](study-plan.md)

## Benchmark identity

- Name: <human-readable>
- Slug: <kebab-case>
- Version: <semantic version>
- Description: <1 paragraph, in the user's words>
- Modality: <text | agentic-fhir | multimodal | blocked: exact requested modality>
- Intended MAST category: <safety / reasoning / agentic /
  multimodal / diagnostic / other>

## MAST compatibility

- Directory shape: `benchmarks/<slug>/` with `build.py` (exporting
  `build()`), `README.md`, and `package/benchmark.json`,
  `package/cases.jsonl`, and `package/asset-manifest.json`.
  Agentic/FHIR v2 also writes `package/env.json` and one
  `package/cohort/<item-id>.fhir.json` asset per case.
  Multimodal v3 also writes `package/attachments.json` and flat,
  hash-bound `package/attachments/<name>` image assets.
  `build.py` loads the strict package through
  `Benchmark.from_package`. The original build sidecar and planning
  artifacts remain in place; README records their roles, digests, and
  safe relative links instead of copying potentially sensitive files.
  A non-public release posture also adds a root `.gitignore` entry for
  `package/cases.jsonl` and a prominent README warning.
  Unsupported scorer adapters can add benchmark-specific files only
  after their gap is resolved.
- Output layout: `results/raw/<slug>/<model>.jsonl`,
  `results/scores/<slug>/<model>.csv`, compiled rows matching the
  MAST CSV shape.
- Submodule-ready: yes.

## Machine-readable build sidecar

_This section summarizes the separate `benchmark-build-spec.json`; it
does not duplicate the JSON or make new clinical decisions._

- File: `benchmark-build-spec.json`
- Schema: <`arisekit.benchmark-build-spec.v1` for text |
  `arisekit.benchmark-build-spec.v2` for Agentic/FHIR |
  `arisekit.benchmark-build-spec.v3` for multimodal PNG/JPEG attachments>
- Source support: <v1: ready local JSONL/CSV | v2: ready local JSONL |
  v3: ready local JSONL plus exact local image inventory | blocked:
  provisional, remote, nested, unsupported media, or other>
- Modality support: <v1: ready text | v2: ready agentic-fhir | v3: ready
  multimodal | blocked: exact requested modality and missing adapter>. Modality
  is separate from MAST category.
- Scorer support: <ready exact-match | ready contains | ready choice |
  ready numeric | v2: ready pass-at-one | v3: ready exact-match for structural
  smoke only | blocked: exact primitive and missing scaffold adapter>
- Source path and SHA-256: <relative path; exact digest | null while blocked>.
  V3 also records every image path, digest, byte size, and media type.
- Data classification: <public | synthetic | deidentified | limited |
  identifiable>
- Release posture: <public | restricted | private | held-out>
- Materialization authorization: <authorized true or false; actor;
  RFC 3339 timestamp; verbatim text>. V3 text explicitly covers copying image
  bytes as well as normalized rows.
- Artifact hashes recorded: <all seven required roles confirmed |
  missing roles>
- Readiness: <ready | blocked>
- Blocking gaps copied into the sidecar: <none | exact list>
- Canonical adapter-gap names: <none | exact source, modality,
  attachment, and scorer primitives required by the build-spec
  contract; no unrelated substitute gaps>
- Reviewed execution allowlist: <exact `allowed_model_routes`; this is
  not provider-disclosure authorization>
- Route-to-provider map: <one `first_sweep` row for every allowed model
  route; the model sets are equal>
- User confirmation copied verbatim: <actor; RFC 3339 timestamp;
  exact text>
- Claim boundary: deterministic local scaffolding only. This does not
  authorize inference, certify privacy or rights, approve clinical
  content, authorize sharing or publication, or admit the benchmark to
  MAST.

### Agentic/FHIR v2 binding

_Complete only when the schema is `arisekit.benchmark-build-spec.v2`.
Otherwise write "N/A."_

- Environment: `fhir-r4-in-memory` /
  `arisekit.env.fhir.FHIREnvironment` / FHIR `R4` /
  `per-item-trial`
- Tool catalog: `arisekit.fhir-tools.v1`
- Allowed tools: <non-empty ordered, duplicate-free reviewed subset>
- Maximum turns: <positive integer>
- FHIR source mapping: `source.field_map.fhir_bundle: "fhir_bundle"`
- Attachment mapping: `null`
- Scorer: `pass-at-one` /
  `arisekit.agentic.PassAtOneScorer` / metric `pass_at_1`
- Condition schema: `arisekit.agentic-pass-condition.v1`
- Required calls: <exact tool names and JSON arguments; all calls required and
  successful>
- Final-response terms: <non-empty substrings; all required;
  case-insensitive matching>
- Cohort binding: <one Bundle per row; valid FHIR item id equals Bundle id;
  Bundle moves to `package/cohort/<item-id>.fhir.json` and is absent from
  normalized `cases.jsonl`>
- Ready governance gate: <classification is public or synthetic; release
  posture is public; explicit materialization authorization present>
- Deferred adapters: <none used | exact gaps for trajectory judge, custom tool
  catalog, remote FHIR environment, richer action-state predicates, multiple
  Bundles, or attachments>

### Multimodal image-attachment v3 binding

_Complete only when the schema is `arisekit.benchmark-build-spec.v3`.
Otherwise write "N/A."_

- Attachment schema: `arisekit.image-attachments.v1`
- Source mapping: `source.field_map.attachments: "attachments"`
- Source row contract: <one to four ordered, duplicate-free flat
  `attachments/<name>.png|jpg|jpeg` paths per row>
- Asset inventory: <non-empty; lexicographically sorted by path; no duplicate
  or case-insensitively duplicate paths; every asset referenced>
- Asset limits: <1 byte to 10 MiB each; 100 MiB total>
- Media support: `image/png`, `image/jpeg`
- Path boundary: <sidecar-relative regular files; no absolute or remote paths,
  data URIs, traversal, or symlinks>
- Byte binding: <each asset has exact path, SHA-256, `size_bytes`, and media
  type; filename, media type, and image signature agree>
- Package binding: <flat `package/attachments/<name>`; exact assets and ordered
  case bindings in `package/attachments.json`; every byte in
  `package/asset-manifest.json`>
- Scorer: `exact-match` / `arisekit.scorer.exact_match` / metric `accuracy`
- Scorer claim boundary: <structural attachment and result plumbing only; not a
  semantic image-report metric and not GREEN>
- Ready governance gate: <classification is public or synthetic; release
  posture is public; verbatim authorization explicitly covers normalized rows
  and copying inventoried image bytes>
- Reviewed model routes: <every route accepts image inputs>
- Deferred adapters: <none used | exact gaps for semantic image-report judge,
  GREEN compatibility, DICOM, remote or non-image attachments, non-public
  images, nested paths, transforms, or a general media pipeline>

## Data governance for scaffolding

- Classification source: <exact section in `compliance-scope.md` or
  `data-profile.md`>
- Classification: <public | synthetic | deidentified | limited |
  identifiable>
- Intended release posture: <public | restricted | private | held-out>
- Materialization decision: <authorized | not authorized>
- Authorizing actor and role: <...>
- Authorization timestamp: <RFC 3339>
- Verbatim authorization text: <exact words authorizing or withholding
  permission to write normalized rows to `package/cases.jsonl`>
- Ready-gate result: <pass | blocked: limited/identifiable data |
  blocked: public posture is inconsistent with classification |
  blocked: materialization is not explicitly authorized | v2 blocked:
  initial Agentic/FHIR adapter is not public/synthetic with public posture | v3
  blocked: image source is not public/synthetic with public posture, or the
  authorization does not explicitly cover copying image bytes>
- Generated package handling: <public posture | v1 non-public: root `.gitignore`
  excludes `package/cases.jsonl` and README warns that the package is
  non-public>
- Provenance boundary: package metadata records classification,
  posture, authorization actor and timestamp, and the SHA-256 of the
  exact authorization text. It does not repeat that text.
- Post-build egress gate: <public package: not required | v1 non-public
  generated package: create and validate
  `arisekit.egress.ProviderDisclosureAuthorization` against the
  SHA-256 of the exact `package/asset-manifest.json` bytes, release
  posture, selected route's provider, and `judge_providers: []`>. Do
  not embed this object in the build sidecar because its
  `generated_bundle_hash` is
  unavailable before scaffolding.
- Authorization trust boundary: <the external record is an auditable
  approval assertion; runtime validates its bindings but does not verify
  a signature, so trust depends on the authorization-file workflow>.

## NOHARM-style blueprint and export

_Complete only when `rubric.md` chose NOHARM-style. Otherwise write
"N/A." This contract records structure and review state; it is not
clinical, rights, privacy, or MAST certification._

### Versioned blueprint

- Schema: `arisekit.benchmark-blueprint.v2`
- Blueprint id / name / version / specialty:
  <id; name; semantic version; specialty>
- `strict_noharm_topology`: `true`
- `expected_variants_per_base`: `10`
- Response contract: <exact pointer to the values in `rubric.md`>
- Judge contract: <id, version, stages, settings, partial-credit
  policy, prompt hashes, schema hashes>
- Aggregation contract: <primary metric, reductions, bootstrap,
  confidence level, weighting>
- Sources: <mapping from the `data-profile.md` source ledger to
  `SourceRecord`; no `rights_basis: unknown` remains; every source has
  a release scope, authorization hash, data owner, and timestamp>
- Case families: <expected count and ordered ids>
- Export family-id format: <letters followed by three digits, for
  example `Card001`; confirmed or unresolved>
- Target review stage: `workflow_complete`
- Named lock and attestation owners: <from `study-plan.md`>
- Access classification: <private | restricted | public>
- Generated access metadata: <explicit classification and authored
  source rights; no inherited public-reference `open: true`>
- Source revision: <immutable revision string>

### Generated bundle

- Exporter: `benchmarks.noharm_reference.export_noharm_bundle`
- Pinned assets type: `PinnedNoHarmAssets`
- Validator: `NoHarmCompatibleBundle`
- Response-prompt derivation: <how the frozen `ResponseContract`
  becomes the exact pinned prompt bytes>
- Approved judge runtime dependency lock:
  `<runtime_dependency_lock_sha256 derived from the reviewed
  dependency-manifest path/hash inventory; dependency bytes are not
  copied into the generated bundle>`
- Generation lineage: `<provider; requested model; provider-returned model;
  family; response ids; generation manifest/code/input hashes; RFC 3339
  timestamp; identifiers and hashes only>`
- Export call: `export_noharm_bundle(blueprint, output_path,
  assets=..., access_classification=...,
  expected_base_cases=...)`
- Output path: <immutable bundle directory>
- Required inventory: `bundle-manifest.json`, `dataset/items.jsonl`,
  per-base `dataset/rubrics/` and per-row
  `dataset/perturbations/`, per-base `guidance/`, `prompts/`,
  pinned `judge/` assets, and `provenance/blueprint.json`,
  `provenance/sources.json`, `provenance/review.json`, and inventoried
  `provenance/generation-lineage.json`.
- Expected base-case count: <N>
- Expected topology: <N families; 11 rows each; variants
  `<base>-0` through `<base>-9`>
- Canonical positive-integer rubric option ids: <confirmed |
  unresolved>

| Pinned asset | Path / name | SHA-256 | Source revision |
| ------------ | ----------- | ------- | --------------- |
| Response prompt | <path; prompt name> | <digest> | <revision> |
| Judge prompt or schema | <path> | <digest> | <revision> |

- Export acceptance: <blueprint and every family workflow
  complete; exactly one harm-of-inaction option per family; all
  variants attested; guidance locked; judge assets match pins>
- Generic package sidecar, if also required:
  `arisekit.package.write_package(..., blueprint=<serialized>,
  write_asset_manifest=True)`. This does not replace the generated
  NOHARM bundle.

### Immutable run manifests

| Field | Frozen value or source |
| ----- | ---------------------- |
| `benchmark_arm` | <reference or generated> |
| `benchmark_content_hash` | <bundle content hash> |
| `prompt_hash` | <response prompt hash> |
| `rubric_hash` | <per-base rubric-set hash> |
| `guidance_hash` | <guidance-set hash> |
| `judge_hash` | <judge asset and declared runtime dependency-lock hash> |
| `code_hash` | <runner / bundle code hash> |
| `model`, `provider`, `model_config` | <exact snapshot, settings, and `runtime_dependency_lock_sha256`> |
| `trials`, `seeds`, `selection` | <values> |
| `source_revision` | <immutable source revision> |

### Three-family synthetic smoke fixture

- Families / taxonomy cells: <three exporter-compatible ids; three
  distinct cells>
- Expected rows: 33
- Fixture review actors: <named test identities>
- Test sequence: <blueprint round trip; compatible export;
  `NoHarmCompatibleBundle` load; stubbed or cheap one-trial run>
- Claim boundary: structural execution only; no clinical
  validation claim.

## Dataset loader spec

- Method: `arisekit.Dataset.<from_jsonl | from_csv | from_hf |
  custom subclass>`
- Source path / repo: <...>
- Build-sidecar status: <v1 supported local JSONL/CSV | v2 supported local
  JSONL | v3 supported local JSONL plus exact PNG/JPEG inventory | blocked;
  exact reason>. No version silently adapts remote, nested, unsupported-media,
  or custom sources.
- Field mapping:

| Source field           | `BenchmarkItem` slot     | Notes              |
| ---------------------- | ------------------------ | ------------------ |
| `<source>`             | `id`                     |                    |
| `<source>`             | `prompt`                 |                    |
| `<source>`             | `ground_truth`           |                    |
| `<source>`             | `metadata`               |                    |
| `<source or none>`     | `attachments`            | v1/v2 require none; v3 requires literal `attachments` |
| `<fhir_bundle or N/A>` | v2 cohort asset           | v2 requires literal `fhir_bundle` mapping |

- System prompt (if any): <verbatim>

## Scorer spec

- Primary primitive: `<arisekit.judges.X | arisekit.scorer.Y |
  compose(...)>`
- Build-sidecar status: <supported `exact-match`, `contains`, `choice`,
  or `numeric` in v1 | supported versioned `pass-at-one` in Agentic/FHIR v2 |
  supported exact-match structural smoke in multimodal v3 | supported
  `rubric-judge` with `arisekit.rubric-judge.v1` for public/synthetic packages | blocked; exact
  primitive and adapter gap>. Do not approximate an unsupported scorer with a
  supported one. In particular, do not describe v3 exact-match as a semantic
  image-report judge or GREEN.
- Dimensions / sub-scores: <list with weights if applicable>
- Judge prompts (if LLM-as-judge): <verbatim; may be multiple>
- Versioned rubric adapter: <criteria, weights, anchors, example judgments,
  pinned provider profiles, and separate judge call/cost reservations; or N/A>
- Disagreement review: <who reviews criterion scores and rationales in
  `judgments.jsonl` and `judge-summary.json`>
- Concordance formula (if expert-panel): <verbatim>
- Pass/fail predicates (if agentic): <verbatim>
- Category breakdown for sub-scores: <from the study plan's
  taxonomy>

## Runner configuration

- Item count (full run): <N>
- Trials per item: <N>
- Parallelism (threads): <default or override>
- Budget ceiling (soft stop): <if any>
- Retry policy: <use framework defaults unless otherwise noted>
- Agent maximum turns: <v2 positive integer | N/A>

## Model list for the first sweep

| Model                   | Provider   | Compatible with data class? | Trials |
| ----------------------- | ---------- | --------------------------- | ------ |
| <gpt-4o>                | OpenAI     | yes / no (reason)           | <N>    |
| <claude-sonnet-...>     | Anthropic  | yes / no                    | <N>    |
| ...                     | ...        | ...                         | ...    |

## Rater tooling handoff

- How raters produce ground-truth: <pre-scored items | live
  panel during a calibration run | pending rater UI>
- Where rater outputs land: <files, fields>
- How the scorer consumes rater outputs: <...>

## Library and scaffold-adapter gaps

| Needed primitive or adapter               | Status        | Owner / issue    |
| ----------------------------------------- | ------------- | ---------------- |
| <e.g. `arisekit.judges.DermaJudgePanel`>  | missing       | <GH issue link>  |
| <e.g. scaffold adapter for an existing scorer> | unsupported by selected build-spec version | <GH issue link> |

If this table is non-empty, CUJ 02 will stall on those gaps.
Address them before starting deterministic scaffolding. Do not generate
placeholder scorer code or substitute a simpler primitive. Use the
canonical build-spec gap names: `arisekit.scaffold.source-adapter.<kind>`,
`arisekit.scaffold.modality-adapter.<modality>`,
`arisekit.scaffold.attachment-adapter.<field>`, or the exact requested
`scorer.primitive`.

## Open questions

- <Anything upstream skills left unresolved>
- <...>

## Acceptance checklist

- [ ] Smoke run: <N> items, one trial, one cheap model, no
  framework errors.
- [ ] Output layout matches MAST shape.
- [ ] Calibration concordance meets the study plan's threshold.
- [ ] Inputs follow the institution-owned data process recorded in
  `compliance-scope.md`; ARISEKit makes no identifier-clearance claim.
- [ ] Implementation plan + artifacts are linked from the
  benchmark's README.
- [ ] `benchmark-build-spec.json` uses v1 for text, v2 for the exact
  Agentic/FHIR adapter, or v3 for the exact multimodal image adapter; it
  references all seven artifact hashes and matches the accepted implementation
  plan.
- [ ] A `ready` v1 sidecar has a materialized local JSONL/CSV source, verified
  source and prompt hashes, an auto-bindable built-in scorer,
  `benchmark.modality: "text"`, no open questions or gaps, a smoke-test route
  in the compliance-derived allowlist, and one provider-bearing first-sweep
  row for every allowed route with no extra routes.
- [ ] A `ready` v2 sidecar has local JSONL, modality `agentic-fhir`, literal
  `fhir_bundle` mapping, null attachments, the fixed FHIR R4 environment and
  tool catalog, a non-empty reviewed allowlist, positive `max_turns`, the
  versioned pass@1 scorer, and valid versioned pass conditions.
- [ ] A `ready` v3 sidecar has local JSONL, modality `multimodal`, literal
  `attachments` mapping, a sorted `arisekit.image-attachments.v1` inventory,
  one to four ordered PNG/JPEG paths per case, and the deterministic exact-match
  scorer for structural smoke testing only.
- [ ] A `ready` sidecar classifies the source as `public`, `synthetic`,
  or `deidentified`, has an explicit `authorized: true`
  materialization record, and uses public release posture only for
  `public` or `synthetic` data.
- [ ] A `ready` v2 sidecar is specifically `public` or `synthetic` with public
  release posture; this initial adapter has no non-public path.
- [ ] A `ready` v3 sidecar is specifically `public` or `synthetic` with public
  release posture, and its verbatim materialization authorization explicitly
  covers copying the inventoried image bytes as well as normalized rows.
- [ ] A non-public v1 scaffold ignores `package/cases.jsonl` at its root,
  displays the data-handling warning in README, and stores only the
  authorization-text digest in package provenance.
- [ ] `allowed_model_routes` is labeled as the reviewed execution
  allowlist, not authorization to disclose data to providers. Any
  non-public generated v1 package requires a
  `ProviderDisclosureAuthorization` after the materialized
  asset-manifest hash exists and before inference.
- [ ] A `blocked` sidecar uses the canonical exact gap primitive for
  every unsupported source, modality, attachment mapping, or scorer
  and produces no partial benchmark scaffold.
- [ ] A refusal to materialize remains blocked and records the actor,
  RFC 3339 timestamp, and exact refusal text; none is null.
- [ ] `arisekit check-benchmark <slug>` passes the package asset,
  `BenchmarkItem`, `build()` factory, and MAST CSV-shape checks.
- [ ] For v2, package checks also pass the cohort, case bindings, full selected
  tool schemas, fixed environment, isolation scope, maximum turns, and
  deterministic trajectory scorer.
- [ ] For v3, package checks also pass `attachments.json`, every flat image
  asset and digest/size/media declaration, ordered case bindings, image
  signatures, package-contained resolution, and deterministic scorer.
- [ ] Build/scaffold emits `runnable-benchmark.json` with the entry
  point, dataset and scorer digests, required assets, environment,
  source revision, planned smoke, and `awaiting_smoke_test` state.
- [ ] The exact planned smoke binds `run-results.json` by digest and
  advances the runnable manifest to `ready` or `blocked` before
  `run-config` is authored.
- [ ] Additional domain-specific criteria: <list>
- [ ] If NOHARM-style: versioned `BenchmarkBlueprint` round-trips
  and reaches `workflow_complete`.
- [ ] If NOHARM-style: each family exports as one base plus exactly
  ten attested perturbations with locked guidance.
- [ ] If NOHARM-style: the three-family fixture exports 33 rows and
  loads through `NoHarmCompatibleBundle`.
- [ ] If NOHARM-style: response and judge bytes match all pinned
  hashes.
- [ ] If NOHARM-style: an inventoried `GenerationLineage` binds the
  provider, requested and returned model identities, family, response
  ids, generation manifest/code/input hashes, and timestamp without
  copying private generation inputs.
- [ ] If NOHARM-style: the blueprint, pinned assets, and run manifests
  bind the same approved
  `runtime_dependency_lock_sha256` without copying private dependency
  files.
- [ ] If NOHARM-style: canonical staged or cohort-pooled judging names
  a separately reviewed pinned batch adapter.

## User confirmation

<Verbatim from the user: "Yes, this matches the benchmark I want
to build" or the nearest honest phrasing. Date and timestamp.>

## Next step

If `benchmark-build-spec.json` is `ready`, run from the ARISEKit
checkout:

```text
arisekit new-benchmark --spec benchmark-build-spec.json
arisekit check-benchmark <slug>
```

These commands create and verify `runnable-benchmark.json`. The build
specification is not proof that the benchmark is runnable.

If it is `blocked`, resolve the recorded library or scaffold-adapter
gaps first. Do not ask a coding agent to invent the missing scorer or
infer fields from this Markdown.

The repository includes a complete worked example under `examples/p0-golden-path/`.

When the author wants to share the implemented benchmark, use
`arisekit export-benchmark benchmarks/<slug> --output <slug>-<version>.zip`.
Carry the reviewed benchmark description into the export and declare any
additional Python dependencies with repeatable `--dependency` arguments.
The generated BENCHMARK.md and MAST_CONTRIBUTION.md explain verified import,
working-copy smoke execution, and the MAST repository/submodule handoff.
Export does not publish the benchmark or establish data rights or MAST admission.

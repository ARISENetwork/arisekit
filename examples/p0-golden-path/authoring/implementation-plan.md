# Implementation plan

_Author:_ P0 golden-path fixture owner  
_Date:_ 2026-09-02  
_Produced by:_ `arisekit/implementation-plan`  
_Upstream:_ [`need-statement.md`](need-statement.md), [`existing-coverage.md`](existing-coverage.md), [`compliance-scope.md`](compliance-scope.md), [`data-profile.md`](data-profile.md), [`rubric.md`](rubric.md), [`study-plan.md`](study-plan.md)  
_Status:_ accepted and ready

## Benchmark identity

- Name: P0 golden-path synthetic routing.
- Slug: `p0-golden-path`.
- Version: `0.1.0`.
- Description: Two synthetic clinical routing labels that prove the reviewed authoring-to-run contract. The benchmark exercises software plumbing only and does not measure clinical performance.
- Modality: text.
- Intended MAST category: clinical-reasoning.

## MAST compatibility

- Directory shape: `benchmarks/p0-golden-path/` with `build.py` exporting `build()`, `README.md`, `runnable-benchmark.json`, and strict `package/benchmark.json`, `package/cases.jsonl`, and `package/asset-manifest.json`. `build.py` loads the package through `Benchmark.from_package`; planning files remain at their authoring paths and are linked with hashes.
- Output layout: `results/raw/p0-golden-path/<run-manifest-sha>/stub__reference.jsonl`, `results/scores/p0-golden-path/<run-manifest-sha>/stub__reference.csv`, and `results/run-results/p0-golden-path/<run-manifest-sha>/stub__reference/run-results.{json,md}`. Compiled rows use the MAST CSV shape.
- Submodule-ready: yes, structurally. This does not establish MAST admission or clinical quality.

## Machine-readable build sidecar

This section summarizes the separate `benchmark-build-spec.json`; it does not replace it or make new clinical decisions.

- File: `benchmark-build-spec.json`.
- Schema: `arisekit.benchmark-build-spec.v1`.
- Source support: ready local JSONL.
- Modality support: ready text.
- Scorer support: ready exact-match.
- Source path and SHA-256: `cases.synthetic.jsonl`; `d5ebf0dadd7c0b1f3974ff804862e006614529fa159ab92e1d3bda804c03ebff`.
- Data classification: synthetic.
- Release posture: public.
- Materialization authorization: authorized `true`; P0 golden-path fixture owner; 2026-09-02T12:05:00Z; "I confirm that the two source rows are wholly synthetic, approved for public repository release, and authorized for materialization into the generated benchmark package."
- Artifact hashes recorded: all seven required roles confirmed; exact digests are stored in the sidecar and generated provenance.
- Readiness: ready.
- Blocking gaps copied into the sidecar: none.
- Canonical adapter-gap names: none.
- Reviewed execution allowlist: `stub/reference` only; this is not provider-disclosure authorization.
- Route-to-provider map: `stub/reference` -> `stub`, one trial; the first-sweep and allowlist model sets are equal.
- User confirmation copied verbatim: P0 golden-path fixture owner; 2026-09-02T12:00:00Z; "I confirm that these accepted artifacts describe the synthetic contract benchmark I want to build."
- Claim boundary: deterministic local scaffolding and execution plumbing only. This does not authorize other inference, certify privacy or rights, approve clinical content, authorize another source or provider, or admit the benchmark to MAST.

## Data governance for scaffolding

- Classification source: `compliance-scope.md`, sections "Data class considered" and "Licensing and redistribution"; corroborated by the `data-profile.md` source ledger.
- Classification: synthetic.
- Intended release posture: public.
- Materialization decision: authorized.
- Authorizing actor and role: P0 golden-path fixture owner and original synthetic-text owner.
- Authorization timestamp: 2026-09-02T12:05:00Z.
- Verbatim authorization text: "I confirm that the two source rows are wholly synthetic, approved for public repository release, and authorized for materialization into the generated benchmark package."
- Ready-gate result: pass.
- Generated package handling: public posture; normalized `package/cases.jsonl` is retained in Git as part of the proof.
- Provenance boundary: package metadata records classification, posture, actor, timestamp, and the SHA-256 of the exact authorization text; it does not repeat the text.
- Post-build egress gate: not required for the public synthetic package. No external route is in the allowlist; `stub/reference` makes no provider call and uses `judge_providers: []` by construction.
- Authorization trust boundary: the approval is an auditable repository assertion, not a cryptographic signature. Its authority is limited to the exact hashed source and public materialization described here.

## NOHARM-style blueprint and export

N/A. `rubric.md` chose MCQ / fixed-answer. Versioned NOHARM blueprints, generated bundles, immutable parity manifests, three-family fixtures, and parity campaign handoffs do not apply.

## Dataset loader spec

- Method: the build-spec v1 local JSONL adapter maps authoring rows, writes the strict package, and runtime uses `arisekit.Dataset.from_package` through generated `build.py`.
- Source path / repo: `examples/p0-golden-path/authoring/cases.synthetic.jsonl` in this repository.
- Build-sidecar status: supported local JSONL; exact source hash is frozen above.
- Field mapping:

| Source field | `BenchmarkItem` slot | Notes |
| --- | --- | --- |
| `case_id` | `id` | required unique string |
| `prompt` | `prompt` | required non-empty synthetic text |
| `reference_answer` | `ground_truth` | single fixed-answer label |
| `setting` | `metadata.setting` | copied metadata value |
| none | `attachments` | build-spec v1 requires none; normalized to `[]` |

- System prompt (verbatim): `Return only the single reference label: A, B, or C.`

## Scorer spec

- Primary primitive: `arisekit.scorer.exact_match`.
- Build-sidecar status: supported `exact-match`.
- Options: `case_sensitive: true`, `strip: true`, `name: accuracy`.
- Dimensions / sub-scores: `overall/accuracy`, weight 1.0.
- Judge prompts: N/A; no LLM judge.
- Concordance formula: N/A; no expert panel.
- Pass/fail predicates: smoke succeeds with 2 completed calls, 0 terminal errors, and accuracy 1.0.
- Category breakdown for sub-scores: N/A; `study-plan.md` taxonomy is fixture coverage only, not a reported clinical sub-score.

## Runner configuration

- Item count (full run): 2.
- Trials per item: 1.
- Parallelism (threads): 1.
- Budget ceiling (soft stop): USD 1.00 total, USD 0.01 per call, 2 calls maximum, known cost required.
- Retry policy: 1 maximum retry with 0-second backoff.
- Inference settings: temperature 0.0 and maximum 8 output tokens.

## Model list for the first sweep

| Model | Provider | Compatible with data class? | Trials |
| --- | --- | --- | ---: |
| `stub/reference` | `stub` | yes - local synthetic reference stub with no provider dispatch | 1 |

No external or clinical-performance sweep is authorized.

## Rater tooling handoff

- How raters produce ground truth: N/A; the fixture owner pre-scored the two original synthetic items.
- Where rater outputs land: N/A for separate outputs; the frozen labels are `reference_answer` in `cases.synthetic.jsonl` and become `BenchmarkItem.ground_truth`.
- How the scorer consumes rater outputs: exact-match reads packaged `ground_truth`; no annotation file or panel aggregation exists.

## Library and scaffold-adapter gaps

| Needed primitive or adapter | Status | Owner / issue |
| --- | --- | --- |

None. Local JSONL, text modality, no attachments, and exact-match scoring are supported by build-spec v1.

## Open questions

- None. A different source, modality, scorer, clinical claim, human study, or provider route requires new upstream review and a new sidecar.

## Acceptance checklist

- [x] Smoke run: 2 items, one trial, local `stub/reference`, no framework errors.
- [x] Output layout matches the MAST shape and retains raw, scores, manifest, and run-inspection evidence.
- [x] Calibration concordance meets the study plan's threshold - N/A because no annotation or concordance claim exists.
- [x] Inputs follow the process in `compliance-scope.md`; they are original synthetic bytes, and ARISEKit makes no identifier-clearance claim.
- [x] Implementation plan and all upstream artifacts are linked from the generated benchmark README.
- [x] `benchmark-build-spec.json` uses `arisekit.benchmark-build-spec.v1`, references all seven artifact hashes, and matches this accepted plan.
- [x] The ready sidecar has a materialized local JSONL source, verified source and prompt hashes, auto-bindable exact-match scorer, text modality, no open questions or gaps, and a smoke route in the allowlist.
- [x] The ready sidecar classifies the source as synthetic, records explicit authorized materialization, and uses a compatible public posture.
- [x] Non-public scaffold controls - N/A because this package is public; no non-public data is authorized.
- [x] `allowed_model_routes` is labeled as an execution allowlist, not disclosure authorization; only the no-egress reference stub is listed.
- [x] Blocked-sidecar exact-gap behavior - N/A because all required v1 adapters exist and readiness is `ready`.
- [x] Materialization-refusal behavior - N/A because the fixture owner explicitly authorized the exact source; any future refusal must remain blocked with complete evidence.
- [x] `arisekit check-benchmark p0-golden-path --verify-linked-provenance` passes package assets, normalized items, generated factory, linked hashes, and MAST CSV-shape checks.
- [x] Scaffolding emits `runnable-benchmark.json` with entry point, dataset and scorer digests, required assets, environment, source revision, and planned smoke in `awaiting_smoke_test` state.
- [x] The exact planned smoke binds `run-results.json` by digest and advances the runnable manifest to `ready`.
- [x] Additional domain-specific criterion: `load_and_verify_run_inspection` re-hashes the retained raw checkpoint and scores successfully.
- [x] NOHARM blueprint round trip - N/A.
- [x] NOHARM eleven-row family export - N/A.
- [x] NOHARM 33-row three-family fixture - N/A.
- [x] NOHARM pinned response and judge hashes - N/A.
- [x] NOHARM generation lineage - N/A.
- [x] NOHARM runtime dependency lock - N/A.
- [x] NOHARM staged judging adapter - N/A.
- [x] NOHARM parity run manifests - N/A.

## User confirmation

P0 golden-path fixture owner, 2026-09-02T12:00:00Z: "I confirm that these accepted artifacts describe the synthetic contract benchmark I want to build."

## Next step

Run from the ARISEKit checkout:

```text
python -m arisekit.cli --benchmarks-dir benchmarks --results-dir examples/p0-golden-path/results new-benchmark --spec examples/p0-golden-path/authoring/benchmark-build-spec.json
python -m arisekit.cli --benchmarks-dir benchmarks --results-dir examples/p0-golden-path/results check-benchmark p0-golden-path --verify-linked-provenance
python -m arisekit.cli --benchmarks-dir benchmarks --results-dir examples/p0-golden-path/results eval p0-golden-path --model stub/reference --limit 2 --trials 1
```

These commands prove structural compatibility and local execution readiness only. They do not validate clinical content, data rights beyond the recorded fixture authorization, privacy compliance, or MAST admission.

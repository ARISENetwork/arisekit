# Python library reference

The public package entry point is `arisekit/__init__.py`. The command-line entry points are registered in `cli.py`. For a runnable introduction, start with the
[text benchmark example](../examples/p0-golden-path/README.md).

## Subpackages

| Subpackage | Contents |
| --- | --- |
| `common/` | Shared infrastructure for the package and its toolkits: JSON and hashing, schemas, safe paths, logging, statistics, model calls |
| `analysis/` | Statistics and analysis: intervals, stress and sweep analysis, synthetic program reports |
| `authoring/` | Benchmark authoring: blueprints, specialty plans and inventories, opportunity and content inventories, source evidence, FHIR generation, compilers, iteration review |
| `evaluation/` | Evaluating generated benchmarks: NOHARM judge contracts; grounding; clinical validation and annotation contracts; privacy signals |
| `fhir/` | FHIR benchmarks: native FHIR tasks, autonomous FHIR generation, review, local workflow, CLI |
| `generation/` | Autonomous benchmark generation: engine, validity, diagnostics, generator iteration and metrics, emulation, specialty and international adapters, SCT/CPC/clinical-arithmetic formats |
| `images/` | Medical image benchmarks: image sources and VQA-RAD, generation, controls, validation, metrics, iteration, selection, policy, uploads |
| `rcq/` | RCQ benchmarks: rating arithmetic (the package itself), generation, sources, proxy-judgment audits |
| `runtime/` | Running benchmarks: agent clients, conversation runner and runner setup, execution and execution adapters, distribution, cost previews, rescoring, model canaries |
| `judges/`, `compare/`, `report/`, `monitor/`, `redteam/`, `env/` | Judge scorers, run comparison, reports, monitoring, red-team scoring, and simulated environments |

## Top-level modules

The modules left at the top level are the core used across benchmark types:
benchmarks, datasets, items and results (`benchmark`, `dataset`, `types`),
models and systems under test (`client`, `sut`, `agentic`, `providers`,
`dispatch`), running and scoring (`runner`, `accounted_runner`, `scorer`),
packages and manifests (`package`, `run_manifest`), and the command line
(`cli`, `launcher`, `workspace`).

Runtime identities hash source files by package-relative path, such as
`generation/autonomous_generation.py`, through
`arisekit.common.hashing.source_sha256`. Moving or editing a hashed file
changes the identity, so runs started before the change do not resume after
it. `python -m` targets a file, so a moved entry point needs its new path.

New reusable components belong in the subpackage for their concern.

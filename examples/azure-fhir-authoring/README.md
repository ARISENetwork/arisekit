# Authoring through a real Azure evaluation

This synthetic integration fixture starts with seven planning artifacts and a
version-2 build specification. The normal CLI generates a portable FHIR
benchmark package and evaluates two cases on `azure/gpt-5-mini`. It requires
no benchmark-specific Python. The records are synthetic, and the planning
artifacts are test inputs rather than records of clinician review.

Configure `AZURE_API_BASE`, `AZURE_API_VERSION`, and Azure credentials in the
execution environment. The verified API version is `2025-04-01-preview`.
Use the private MAST VM when the endpoint requires the MUSC Azure network.
Keep credentials out of the source fixture and generated package.

From the repository root, use a fresh output directory:

```sh
mkdir -p outputs/azure-authoring
cp -R examples/azure-fhir-authoring/authoring outputs/azure-authoring/authoring
arisekit --benchmarks-dir outputs/azure-authoring/benchmarks --results-dir outputs/azure-authoring/results new-benchmark --spec outputs/azure-authoring/authoring/benchmark-build-spec.json
arisekit --benchmarks-dir outputs/azure-authoring/benchmarks --results-dir outputs/azure-authoring/results check-benchmark azure-fhir-authoring --verify-linked-provenance
arisekit --benchmarks-dir outputs/azure-authoring/benchmarks --results-dir outputs/azure-authoring/results eval azure-fhir-authoring --model azure/gpt-5-mini --limit 2 --trials 1
```

The `eval` command makes paid Azure calls. The plan selects two cases, one
trial, one worker, at most three turns per case, and a 1,024-token completion
limit. Temperature is omitted. The runner requires known cost and checks a
$0.02 budget between item attempts; this is not an Azure billing cap. The
fixed case and turn counts bound the run to six model calls, excluding
provider-internal retries. There is no LLM judge in this example.

The automated equivalent additionally checks zero-call resume, preserved
smoke evidence, and package portability after removing the authoring inputs:

```sh
ARISEKIT_LIVE=1 python -m pytest tests/test_live_authoring.py -v -s -o junit_family=xunit1 --junitxml=outputs/azure-authoring.xml
```

The test always uses the route and limits in this fixture. The model and
reasoning-effort overrides for `tests/test_live_smoke.py` do not configure the
generated CLI benchmark. The CLI consumes Azure settings through LiteLLM's
normal environment handling.

Inspect the generated `runnable-benchmark.json`, `package/env.json`, cohort
assets, result report, score CSV, and raw trajectory checkpoints. A successful
run moves execution readiness to `ready`. The readiness receipt references an
immutable copy under `results/smoke-evidence/`; the ordinary result summary can
then reflect subsequent resume operations without changing the original
receipt's bytes.

This validates the local plan-to-evaluation path. The hosted UI, planning
conversation, clinical validity, and benchmark admission remain outside the
test's scope.

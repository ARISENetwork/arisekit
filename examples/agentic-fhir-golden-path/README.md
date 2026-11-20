# Agentic/FHIR example

This example runs synthetic chart-based tasks without a provider call or
benchmark-specific Python. Its authoring directory contains seven accepted
planning artifacts, a local JSONL source with one embedded FHIR R4 Bundle per
row, and a benchmark build specification.

From the repository root, copy the fixture to a writable directory and run:

```text
arisekit new-benchmark --spec <copy>/authoring/benchmark-build-spec.json
arisekit check-benchmark agentic-fhir-golden-path --verify-linked-provenance
arisekit eval agentic-fhir-golden-path --model stub/reference --limit 2 --trials 1
```

The scaffold extracts the Bundles into the package cohort, binds the exact
tool schemas and case mapping in `env.json`, records a trajectory, scores the
versioned pass condition, and advances the runnable manifest to `ready`.

This proves structural execution only. It does not establish clinical quality
or MAST admission.

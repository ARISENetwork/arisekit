# Text benchmark example

Build and evaluate two synthetic tasks without provider calls. First complete
[Python setup](../../docs/getting-started.md#python). From the repository root:

```sh
arisekit_example_root=$(mktemp -d)
arisekit --benchmarks-dir "$arisekit_example_root/benchmarks" new-benchmark \
  --spec examples/p0-golden-path/authoring/benchmark-build-spec.json
arisekit check-benchmark "$arisekit_example_root/benchmarks/p0-golden-path" --verify-linked-provenance
arisekit --benchmarks-dir "$arisekit_example_root/benchmarks" --results-dir "$arisekit_example_root/results" \
  eval p0-golden-path --model stub/reference --limit 2 --trials 1
```

The temporary directory contains the generated benchmark, responses, scores,
and run reports. The offline stub returns reference answers. This demonstrates
execution and scoring, not model performance or clinical validation.

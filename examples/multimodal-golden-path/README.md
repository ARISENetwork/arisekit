# Multimodal example

This example runs a synthetic image-based task without a provider call or
benchmark-specific Python. Its authoring directory contains seven accepted
planning artifacts, one local JSONL case, one generated PNG image, and a
benchmark build specification.

From the repository root, copy the fixture to a writable directory and run:

```text
arisekit new-benchmark --spec <copy>/authoring/benchmark-build-spec.json
arisekit check-benchmark multimodal-golden-path --verify-linked-provenance
arisekit eval multimodal-golden-path --model stub/reference --limit 1 --trials 1
```

The scaffold verifies and copies the image bytes, preserves each case's
ordered attachment references, binds the package-local images before model
dispatch, and advances the runnable manifest to `ready` after the structural
smoke passes.

The image is an AI-generated synthetic radiograph-style phantom. This fixture
proves attachment portability and execution only. It is not patient data, a
diagnostic example, clinical validation, or evidence of MAST admission.

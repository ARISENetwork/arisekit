# Implementation plan

_Status:_ accepted

## Benchmark identity

Build `agentic-fhir-golden-path` as a MAST-compatible `agentic-fhir` package.

## Dataset and environment

Load the local JSONL, extract each `fhir_bundle`, isolate an in-memory FHIR R4
environment per item and trial, and expose only `get_patient` from
`arisekit.fhir-tools.v1`.

## Scorer and runner

Bind the versioned pass-at-one trajectory scorer, allow at most three agent
turns, and use the existing runner with two worker threads.

## Acceptance

The normal plan to package to check to smoke path must reach `ready` without
fixture-specific code or a network call.

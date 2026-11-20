# Implementation plan

Build `azure-fhir-authoring` from the seven synthetic planning artifacts and
the local JSONL using `arisekit.benchmark-build-spec.v2`. The source contains
two independent synthetic patient records. Extract each FHIR Bundle into its
own package cohort asset, bind the case mapping and exact `get_patient` tool
schema, and use a fresh in-memory FHIR R4 environment per item and trial.

Bind `arisekit.agentic.PassAtOneScorer` and the versioned required-call plus
final-response pass condition. Use only the reviewed `azure/gpt-5-mini` route
with the limits in the study plan. Credentials and the private Azure endpoint
come from the execution environment and must not enter the authored package.

Exercise the normal `new-benchmark`, `check-benchmark`, and `eval` commands.
Retain package hashes, turn checkpoints, final trajectories, MAST score CSV,
run manifest, result bundle, and readiness receipt. Copy the generated package
away from its authoring inputs and verify it still loads. Replay the exact
run and verify zero new inference and identical response checkpoints.

The user requested this Azure authoring-flow development test. The planning
artifacts are synthetic integration fixtures, not clinician review records.

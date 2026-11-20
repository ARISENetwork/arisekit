# Implementation plan

_Status:_ accepted

## Benchmark identity

Build `multimodal-golden-path` as a MAST-compatible `multimodal` package.

## Dataset and attachments

Load the local JSONL, require one or more ordered PNG or JPEG references per
case, verify every declared image by path, hash, byte size, media type, and
file signature, then copy the bytes into the package.

## Scorer and runner

Bind the deterministic exact-match scorer and use the existing runner. Keep
semantic image-report judging out of this attachment-only slice.

## Acceptance

The normal plan to package to check to smoke path must reach `ready` without
fixture-specific code or a network call.

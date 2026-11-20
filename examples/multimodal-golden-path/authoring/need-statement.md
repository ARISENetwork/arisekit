# Need statement

_Status:_ accepted

## Problem

Medical benchmark authors need a portable way to attach a reviewed local image
to an evaluation case without writing benchmark-specific copy or loading code.

## Outcome

Success means the packaged case presents the exact ordered image bytes to the
model runtime and retains no dependency on the authoring directory.

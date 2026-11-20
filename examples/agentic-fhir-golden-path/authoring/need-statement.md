# Need statement

_Status:_ accepted

## Problem

Primary-care benchmark authors need a portable way to test whether a model can
retrieve the correct synthetic patient record through a reviewed FHIR tool.

## Population and outcome

The fixture uses two wholly synthetic patients. Success requires the exact
patient lookup and a response that contains the expected family name.

# Study plan

_Status:_ accepted

## Structural smoke

Run the single case for one trial with `stub/reference`. The stub makes no
provider call, but the package-bound multimodal SUT must still resolve, verify,
read, and encode the attached image before returning the reference response.

## Claim boundary

Passing this smoke proves transport and runtime wiring only. It is not a test
of diagnosis, image understanding, privacy, rights, or clinical validity.

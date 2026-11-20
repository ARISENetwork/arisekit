# Study plan

This is a synthetic software integration test of the local authoring flow.
Run the two cases once on `azure/gpt-5-mini`, with one worker, at most three
agent turns per case, and a 1,024-token completion limit per model call.
Omit temperature so the deployment can use its supported default. Use no
LLM judge: the versioned deterministic pass condition scores each trajectory.

The runner budget is $0.02, with known cost required and at most six model
calls across the two three-turn cases. The budget is checked by the runner
between item attempts; it is not an Azure billing cap or a per-turn reservation.
There is one runner attempt per case. Provider-level retry behavior is separate.

Both cases must complete without errors, each must score pass@1 = 1, and the
runnable manifest must reach `ready`. Replaying the same evaluation must reuse
both completed cases without inference. Check the generated package after
removing access to the original authoring inputs.

This test does not measure clinical validity, novelty, comparative model
quality, or clinician usability. It starts from an authored plan and does not
simulate the seven-stage planning conversation or hosted UI.

# Rubric

_Status:_ synthetic integration fixture

## Chosen scorer

Use `arisekit.agentic.PassAtOneScorer` with
`arisekit.agentic-pass-condition.v1`.

## Pass condition

Every case requires one successful `get_patient` call with exact arguments and
the expected family name in the final response. The requirements use AND
semantics.

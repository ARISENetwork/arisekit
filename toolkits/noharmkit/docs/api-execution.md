# API execution

API Mode uses OpenRouter for model calls. Scoring runs locally without API credits.

## Local runtime

Use the Python environment from the [local setup guide](agent-skills.md#manual-setup).
Set `OPENROUTER_API_KEY` in the server environment. The app checks availability
before execution.

## Model setup

Choose models and supported reasoning levels in API setup. Multiple drafting
models require an integrator; models under test always respond independently.
Autograding defaults to one judge. Saving settings makes no model calls.

## Responses display

Responses shows the selected models, reasoning levels, and collection status:

- **Pending:** expected responses are missing.
- **Complete:** every expected response succeeded.
- **Failed:** a stored response contains an error.
- **Different settings:** saved responses used another configuration.

## Checkpoints

Completed calls are saved. **Stop after current call** checkpoints the active
call before stopping. Closing the page stops execution at the next completed checkpoint.

## Recovery

- Use **Review saved work** after an interrupted run. Inspection makes no model calls.
- Resume compatible saved work after review; remaining model calls use API credits.
- Use **Start a new run** for changed settings or incompatible outputs.

## Workflow safeguards

Existing projects and results remain intact. Regrading uses the selected rubric
version; earlier judgments remain recorded.

See the [implementation reference](api-execution-reference.md) for configuration
contracts and recovery behavior.

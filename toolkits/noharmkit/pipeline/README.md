# Pipeline

The answer-table workflow runs through `tools/noharm.py` from the repository root. Start with the [runbook](../docs/runbook-e2e-mvp.md) and [agent setup](../docs/agent-skills.md). Command-line argument checks and `.env` loading live in [tools/cli.py](../tools/cli.py).

| Module | Purpose |
|---|---|
| [backends.py](backends.py) | Backend names, routes, and default models; the transports and retries live in [arisekit/common/llm.py](../../../arisekit/common/llm.py) |
| [skillrun.py](skillrun.py) | Skill prompts and validated JSON model calls |
| [answer_table_checks.py](answer_table_checks.py) | Validation gate for generated rubrics |
| [e2e/project.py](e2e/project.py) | Project folder layout, reading, and writing |
| [e2e/records.py](e2e/records.py) | Shapes of the stored JSON records |
| [e2e/rubric.py](e2e/rubric.py) | Rubric types, standard questions, and the views models see |
| [e2e/generate.py](e2e/generate.py) | Generate stage |
| [e2e/committee.py](e2e/committee.py), [e2e/rand.py](e2e/rand.py) | Harm committee and RAND-style panel |
| [e2e/judge.py](e2e/judge.py) | Judge stage |
| [e2e/score.py](e2e/score.py) | Score stage and report |
| [e2e/view.py](e2e/view.py) | Local viewer launch |
| [e2e/constants.py](e2e/constants.py) | Kit and repository paths. Shared JSON, hashing, schema, path, and logging helpers live in [arisekit/common](../../../arisekit/common/) |

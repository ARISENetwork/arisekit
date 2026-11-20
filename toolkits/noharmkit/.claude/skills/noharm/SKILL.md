---
name: noharm
description: Run the NOHARMKit rubric pipeline (import, generate, rate, inference, judge, score) in a project. Use when the user asks to build or run a rubric-based benchmark end to end.
---

Read `docs/agent-skills.md`, then `docs/runbook-e2e-mvp.md`. Resolve the named project and requested scope. For a new project, follow `.claude/skills/noharm-new-project/SKILL.md`.

When asked for the next step, inspect only that project's files. Identify the earliest missing, failed, or stale prerequisite, explain what it needs, and run it when inputs and authorization are available. Do not run the full pipeline for a single-stage or status request.

For stage work, read the matching `.claude/skills/noharm-*/SKILL.md`: `import-cases`, `rubrics`, `responses`, `autograding`, or `scores`. Use the user's cases and models, not the runbook's demo defaults. Keep the project path explicit.

Use the shared execution and model-route rules in `docs/agent-skills.md` and the selected stage's defaults. The default committee includes paid OpenRouter calls; do not enable it implicitly. After `generate`, report each `answer-tables/<ID>.run<k>.status.json`. After `score`, show `results/report.md`.

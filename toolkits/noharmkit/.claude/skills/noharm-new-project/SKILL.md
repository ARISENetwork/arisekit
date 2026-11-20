---
name: noharm-new-project
description: Create a new NOHARM benchmark project and prepare its dataset import. Use for a new project rather than switching to or running an existing benchmark.
---

Read `docs/agent-skills.md` for execution rules and dataset format.

Projects live in `projects/` in this repository. Ask for a name when missing. Use 1-64 lowercase letters, digits, or hyphens, beginning with a letter or digit.

From the repository root, run:

```bash
.venv/bin/python tools/noharm.py create PROJECT_PATH
```

This creates `cases/`, empty `items.jsonl`, and provenance, with `provenance.trials` defaulting to 1. If the user requests repeated trials, add `--trials N` with a positive integer. The count may also be set before first collection; once collection records exist, changing it requires a new project/run. If the path exists, offer to select it or choose another name; never replace or delete it.

If the user supplied cases, read `.claude/skills/noharm-import-cases/SKILL.md` and import only those cases. Otherwise ask for the source after creation. An empty project is valid. Do not invent cases or solutions, or start model calls.

Verify the files and parse `items.jsonl`. Return the project path and imported case count. Tell the user to refresh the Dashboard and choose the new name in the Project dropdown. If the viewer is not running, use the runbook's `view` command against the projects root, not the individual project.

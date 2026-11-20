# Synthetic UTI demo

Canonical fixture for both **demo** and the walkthrough: Case-001, supplied
solutions and errors, one draft rubric (`Case001.run2`), and authored responses
and mappings for hypothetical Models A, B, and C. Scores are deterministic
teaching examples, not measured performance or clinician validation.

## Sources

| Path | Content |
| --- | --- |
| `cases/Case001.json` | Task, solutions, errors; also used by typing animations |
| `answer-tables/Case001.run2.json` | Rubric, with status and provenance alongside |
| `results/responses/` | Authored model responses |
| `results/judge/` | Prepared mappings with checked evidence |
| `results/*_scored.jsonl` | Deterministic scores |

## Explore

Select demo and follow the pipeline. Model B omits pregnancy testing and return
precautions; Model C uses the conditional TMP-SMX option with its required parts.
Avoiding opioids alone does not match an explicit no-additional-treatment option.

## Walkthrough

`/noharm/tutorial` uses the same records and full editor through
`app/lib/uti-tutorial-benchmark.ts`. Practice edits cannot save a reviewed project
rubric. Tests compare records and recompute scores across both views.

## Sample import

Upload [imports/synthetic-import.csv](imports/synthetic-import.csv) into a new
project to test CSV parsing and multiple acceptable solutions.

## Copy

From `app/`, copy active files unchanged, excluding history. Destination must be new:

```bash
node --import tsx scripts/build-uti-demo.ts /absolute/path/to/new-demo
```

Recompute from the repository root; neither command makes model calls:

```bash
.venv/bin/python tools/noharm.py score /absolute/path/to/new-demo
```

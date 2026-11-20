---
name: noharm-import-cases
description: Import supplied tasks and solutions into a named NOHARM project. Use for dataset preparation and import without rubric generation or evaluation.
---

Read `docs/agent-skills.md`. Resolve the exact project path and source selection before writing.

For JSON cases, require nonempty `presentation` and `recommendations` strings. `presentation` stores the Task and `recommendations` the Solution. The filename is the case ID, with no hyphens, path separators, or `Ex` prefix. Verify all selected cases before importing. Keep sources unchanged. For a supplied CSV or document, map task and solution fields into separate staged JSON files; ask when a field mapping or solution is missing. Never invent a solution.

For viewer datasets, map `Task` (`task`, `input`, or `presentation`) to `presentation` and `Solution` (`solution`, `solutions`, `reference`, or `recommendations`) to `recommendations`. Field names are case-insensitive. CSV stores multiple acceptable solutions in one Solution field separated by literal `SOLUTION:`; JSON may supply an array of solutions. Preserve each solution's wording and represent them as acceptable alternatives in the staged Solution string, not cumulative requirements. For staged viewer records, store the original source file path in `source_provenance.source_file` and the distinct supplied solutions in `source_provenance.supplied_solutions`, so the viewer can identify processed uploads and display the original solutions separately from error criteria. Retain supplied IDs and source provenance; if an ID cannot be used as a filename, resolve its mapping before import.

Preserve optional `Errors` text or string arrays and supplied harm levels as author-provided criteria alongside the staged source. They are not clinician validation. When handing off to `noharm-rubrics`, include these criteria explicitly; the generation command does not automatically read an `errors` field. Keep the original file unchanged and keep solutions and criteria out of tested model tasks.

When a supplied case has no ID, assign generic sequential IDs `Case001`, `Case002`, and so on, displayed in the viewer as `Case-001`, `Case-002`. Start after the highest existing `Case` sequence number in the selected project and skip any occupied IDs, including staged cases. Do not derive names from diagnoses or other source content. Preserve supplied IDs and existing records.

For a viewer edit supplied with `source_item_id`, preserve that origin in source provenance and import under its new ID. Never replace the origin case or relabel its existing rubrics, responses, or judgments.

If an existing case ID differs from the source, surface the collision before replacing it. Import only specified cases; do not import unrelated data.

```bash
.venv/bin/python tools/noharm.py import PROJECT_PATH --item ITEM_ID --inputs-dir SOURCE_DIRECTORY
```

Always provide `--inputs-dir` with the supplied source directory. Check the copied source record, single matching collection record, and recorded source provenance. `items.jsonl` must contain the task without exposing the solution to tested models. Report imported IDs, source path, and rejected cases. Refresh Dataset to inspect the import.

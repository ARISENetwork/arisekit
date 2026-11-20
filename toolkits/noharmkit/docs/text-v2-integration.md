# Rubric format and compatibility

NOHARMKit supports current rubrics alongside older answer tables. Projects retain
their selected format and scorer; existing records are not converted in place.

## Import

Create the project and import its Task and Solution first. From the ARISEKit root,
preview a rubric import before writing it:

```sh
scripts/dev/.venv/bin/python scripts/noharm.py import-rubric \
  toolkits/noharmkit/projects/my-project --case Case001 --file /path/Case001.json --dry-run
```

Remove `--dry-run` to import. The importer creates a new version, preserves the
source and its hash, and refuses overwrites. Importing or saving does not establish
clinical review.

## Validation and scoring

Drafts may retain unresolved ratings; scoring requires resolved values. Consult
[authoring rules](contracts/rubric-authoring-rules.md) for the exact format and
[API execution](api-execution.md) for running the pipeline.

The [implementation reference](rubric-compatibility-reference.md) records validator
and editor provenance and compatibility behavior.

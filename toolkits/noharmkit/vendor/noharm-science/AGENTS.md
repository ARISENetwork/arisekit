# Immutable noharm-science snapshots

Each commit-named directory is a verbatim Git archive of explicitly selected
paths from noharm-science. Treat every payload file and PROVENANCE.json as
read-only. Never patch, format, regenerate, or recalibrate these snapshots.
Import a different upstream commit into a new directory instead.

Keep adapters, tests, and verification tools outside the snapshots. Do not run
Python with bytecode writes enabled inside them. Source repository working-tree
files are never import inputs.

The rubrics are draft references pending physician review and may be
recalibrated. Do not represent import, structural validation, or model agreement
as clinical approval. Existing pipeline pins and historical results remain
separate unless a new integration is explicitly authorized.

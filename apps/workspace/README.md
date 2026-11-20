# Local results workspace

The Python wheel includes this interface. After installing ARISEKit, run
`python -m arisekit.launcher` to import an authoring ZIP. To inspect a benchmark
already on disk, run:

```sh
python -m arisekit.workspace --benchmark benchmarks/YOUR-SLUG --authoring path/to/authoring --results results
```

Open the launch URL printed by the runner. The interface reads the benchmark's
local evidence and supports cost preview, re-scoring, and execution.

## Rebuild

From the repository root, run `npm run bootstrap` and `node apps/workspace/build.mjs`.
The build uses the toolkit's locked frontend dependencies and writes the wheel
assets to `arisekit/workspace_ui/`, alongside the bundled software licenses.

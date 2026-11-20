# First Do NOHARM public-benchmark adapter

This adapter turns an accepted First Do NOHARM catalog match into a checked-in
ARISEKit command. It validates and fingerprints a local copy of the official
30-case public release, then launches that release's own `run.py` or `score.py`.
The official scorer remains authoritative because it is a staged,
cohort-pooled judge and is not equivalent to an ARISEKit per-item scorer.

## Prepare the official release

Obtain the public First Do NOHARM release from the source linked in the
[catalog](../../skills/existing-benchmark-search/catalog/public-benchmarks.md),
install its `requirements.txt`, copy its `.env.example` to `.env`, and configure
the candidate-model and judge credentials described by its README. Do not put
credentials in `existing-coverage.md` or pass them as command arguments.

Set `<NOHARM_ROOT>` below to the directory that directly contains `run.py`,
`score.py`, `dataset/`, `guidance/`, `prompts/`, and `judge/`.

## Inspect without making provider calls

```sh
arisekit public-benchmark noharm --source <NOHARM_ROOT> inspect
```

Inspection verifies the public topology, required assets, judge pins, and
content hashes. It prints the validated bundle SHA-256 and upstream help
commands. It does not run model inference or scoring.

## Run the recommended public protocol

Review `config/models/example.yaml` in the public release and set its model
route. Then run inference:

```sh
arisekit public-benchmark noharm --source <NOHARM_ROOT> run -- \
  --model-config config/models/example.yaml \
  --benchmark-config config/benchmark.yaml \
  --k 5 \
  --open-only
```

Score the completed responses:

```sh
arisekit public-benchmark noharm --source <NOHARM_ROOT> score -- \
  --model-config config/models/example.yaml \
  --benchmark-config config/benchmark.yaml \
  --k 5
```

Arguments after `--` go literally to the official entry point. To validate and
print a command without executing it, put `--dry-run` before the action:

```sh
arisekit public-benchmark noharm --source <NOHARM_ROOT> --dry-run run -- \
  --model-config config/models/example.yaml \
  --benchmark-config config/benchmark.yaml \
  --k 5 \
  --open-only
```

The official run kit writes its normal resumable response and score artifacts.
Run the two commands once per model configuration for a multi-model comparison.

## Limits and claim boundary

- The adapter is a validated launcher, not a copy of the public data and not a
  replacement scorer. It does not download the release, install its Python
  dependencies, create model configuration, or manage credentials.
- Candidate-model inference and the default match-and-review Gemini judge make
  provider calls and incur cost. `inspect` and `--dry-run` do not.
- The upstream runner owns output paths, checkpoint/resume behavior, cost
  reporting, and model configuration. These runs do not use ARISEKit's generic
  `Benchmark` runner or `arisekit eval` result manifest.
- Validation establishes compatibility with the expected public 30-case,
  330-row release. It does not establish clinical validity, reproduce a private
  cohort, or guarantee identical results from mutable preview judge routes.
- Run only a trusted official checkout. The `run` and `score` actions execute
  Python code from the supplied directory without a shell.

# Run configuration

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/run-config`
_Run ID:_ <slug or uuid>

## Benchmark target

- **Benchmark:** <cpc-bench | noharm | sctbench | rexrank | medagentbench | builder-draft:<title>>
- **Dataset source:** <jsonl path | csv path | hf dataset id | builder draft ref>
- **Scorer:** <built-in name | custom scorer module path>
- **Agentic loop:** <no | yes — tool definitions at <module path>>

## Runnable benchmark contract

- **Manifest:** `runnable-benchmark.json`
- **Schema:** `arisekit.runnable-benchmark.v1`
- **Canonical SHA-256:** <digest>
- **Origin:** <builder | curated-roster>
- **Readiness:** <ready | awaiting_smoke_test for exact smoke only>
- **Entry point:** <relative path:callable>
- **Dataset SHA-256:** <digest>
- **Scorer SHA-256:** <digest>
- **Source revision:** <revision>
- **Environment:** <exact recorded values>
- **Required assets verified:** <yes | no; no blocks configuration>

## Models

| # | Model string | Provider | Custom callable path |
| - | ------------ | -------- | -------------------- |
| 1 | <e.g. gpt-5.2> | <litellm-detected> | — |
| 2 | <e.g. claude-sonnet-4-20250514> | <litellm-detected> | — |
| 3 | <e.g. mygateway:medgemma-27b> | custom | <arisekit_extensions.medgemma_client> |

## Trials and parallelism

- **Trials per item:** <integer, default 1>
- **Threads:** <integer, default 20>
- **Max retries per request:** <integer, default 3>

## Budget caps

- **Cost cap (USD):** <number | none>
- **Wall-clock cap (minutes):** <number | none>
- **Halt-on-cap behavior:** dispatch stops; in-flight requests
  complete; resume submits the same config again.

## Schedule

- **Mode:** <now | at | after>
- **Run at:** <YYYY-MM-DDTHH:MM:SSZ | n/a>
- **Run after run id:** <run id | n/a>

## Output target

- **Results root:** <results/ | custom path>
- **Raw JSONL path:** `<root>/raw/<benchmark>/<model>.jsonl`
- **Scored CSV path:** `<root>/scores/<benchmark>/<model>.csv`
- **Compiled CSV path:** `<root>/compiled.csv` (suite only)

## Projected cost and duration

- **Items:** <count>
- **Total requests:** items * trials * models = <n>
- **Approx cost:** <USD estimate, optional>
- **Approx wall-clock at <threads> threads:** <duration estimate, optional>

## Resume contract

This config is resume-by-default. Kill and restart at any time:
submitting the same config picks up at the next uncompleted item ×
trial. The on-disk JSONL at the raw path is the source of truth.

## Notes for the next reviewer

<Anything the runner, the monitor, or `run-inspect` needs to
know that does not fit elsewhere. Optional.>

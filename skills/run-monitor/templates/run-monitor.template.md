# Run monitor snapshot

_Author:_ <user name>
_Date:_ <YYYY-MM-DD HH:MM:SSZ>
_Produced by:_ `arisekit/run-monitor`
_Run ID:_ <slug or uuid>
_Upstream:_ [`run-config.md`](run-config.md)

## Run identity

- **Benchmark:** <roster id or builder-draft:<title>>
- **Models:** <model1, model2, ...>
- **Trials per item:** <n>
- **Started at:** <YYYY-MM-DDTHH:MM:SSZ>
- **Snapshot at:** <YYYY-MM-DDTHH:MM:SSZ>

## Progress

| Metric | Value |
| ------ | ----- |
| Items completed | <n> / <total> |
| Trials completed | <n> / <total> |
| Wall-clock elapsed | <duration> |
| Projected remaining | <duration> |

## Cost burn

| Metric | Value |
| ------ | ----- |
| Running total (USD) | <n> |
| Projected at current rate (USD) | <n> |
| Configured cap (USD) | <n | none> |
| Distance to cap (USD) | <n | n/a> |

## Partial metrics

| Model | Category | Metric | N | Value | CI |
| ----- | -------- | ------ | - | ----- | -- |
| <model1> | overall | <name> | <n> | <value> | <ci> |
| <model1> | <category> | <name> | <n> | <value> | <ci> |
| <model2> | overall | <name> | <n> | <value> | <ci> |

Confidence interval widens or narrows with N. With `trials = 1`,
CI is reported as 0; that is the absence of a trial axis, not a
confidence claim.

## Error stream

| Class | Count | Models affected | Example item |
| ----- | ----- | --------------- | ------------ |
| <timeout | rate-limit | scorer-error | refusal | other> | <n> | <model list> | <item id> |

### Terminal failures (post-retry)

| Item ID | Model | Class | Message |
| ------- | ----- | ----- | ------- |
| <id> | <model> | <class> | <one-line message> |

## Verdict

- [ ] Let it cook
- [ ] Pause (resume later, same config)
- [ ] Kill (resubmit after fixing <...>)
- [ ] Done

**Reasoning.** <One paragraph. Reference the partial metrics, the
cost burn, and the error pattern. Cite the resume contract if
killing.>

## Action

- **Next step:** <wait for next snapshot | pause via UI | kill via UI | edit run-config.md and resubmit | hand off to run-inspect>
- **Resume contract:** Kill is safe; the same `run-config.md`
  submitted again picks up at the next uncompleted item.

## Notes for the next reviewer

<Anything `run-inspect` or a collaborator needs to know about
this run that does not fit elsewhere. Optional.>

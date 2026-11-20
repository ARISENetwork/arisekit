# Authoring workflow reference

The local coding-agent workflow creates the artifacts shown below. Start with [guided authoring](README.md) or [choose a kit](../docs/kits.md).

## Pipeline overview

```
needs-analysis  ->  existing-benchmark-search  ->  compliance-intake
       |                                                   |
       v                                                   v
 need-statement.md                          compliance-scope.md
                                                   |
                                                   v
                                           data-intake
                                                   |
                                                   v
                                          data-profile.md
                                                   |
                                                   v
                                         rubric-design
                                                   |
                                                   v
                                             rubric.md
                                                   |
                                                   v
                                          study-design
                                                   |
                                                   v
                       study-plan.md + annotation-study-policy.json
                                                   |
                                                   v
                                      implementation-plan
                                                   |
                                                   v
                         implementation-plan.md + benchmark-build-spec.json
                                                   |
                                                   v
                                      build / scaffold
                                                   |
                                                   v
                                     runnable-benchmark.json
                                                   |
                                                   v
                              run-config -> run-monitor -> run-inspect
                                                   |
                                                   v
                            run-results.json + run-results.md
                                                   |
                                                   v
                         results-iteration -> owning authoring stage
                                                   |
                                                   v
                              release-writeup (optional publication)
```

If `existing-benchmark-search` finds a match, it writes
`existing-coverage.md` and short-circuits the rest of the chain.
The [coverage-search instructions](existing-benchmark-search/SKILL.md) define the handoff to the selected benchmark.

Every completed run produces universal result artifacts. The
`release-writeup` stage runs only when the user chooses a publication
path and the complete Builder provenance stack is available. Users
who only want a plan can stop at implementation-plan; users who only
want run results stop at run-inspect.

## Stages

| Stage  | Skill directory                                            | Hands off                  |
| ------ | ---------------------------------------------------------- | -------------------------- |
| 1      | [needs-analysis/](needs-analysis/)                         | `need-statement.md`        |
| 2      | [existing-benchmark-search/](existing-benchmark-search/)   | `existing-coverage.md` or passthrough |
| 3      | [compliance-intake/](compliance-intake/)                   | `compliance-scope.md`      |
| 4      | [data-intake/](data-intake/)                               | `data-profile.md`          |
| 5      | [rubric-design/](rubric-design/)                           | `rubric.md`                |
| 6      | [study-design/](study-design/)                             | `study-plan.md`            |
| 7      | [implementation-plan/](implementation-plan/)               | `implementation-plan.md`, `benchmark-build-spec.json` |
| After a run | [results-iteration/](results-iteration/)               | reviewed route to stages 4-6, new saved version |
| Optional publication | [release-writeup/](release-writeup/)         | `writeup.md`               |

Evidence-route skills:

| Route | Skill directory | Hands off |
| ----- | --------------- | --------- |
| Portfolio | [portfolio-gap-analysis/](portfolio-gap-analysis/) | `portfolio-opportunity.md`, `opportunity.json` |
| Stress design | [target-stress-design/](target-stress-design/) | `target-stress-plan.md`, `stress-spec.json` |
| Stress validation | [target-stress-validation/](target-stress-validation/) | `stress-validation.md`, `stress-validation.json`, `stress-bootstrap.json` |

Each directory contains a `SKILL.md` with the Claude Code frontmatter
and the Socratic prompt, plus any supporting templates.

## Case Studio flow (item authoring, parallel to the main pipeline)

Use these skills to develop a single benchmark item.

```
case-stem-authoring  ->  rubric-design  ->  case-evaluate  ->  case-fit-check
       |                       |                  |                    |
       v                       v                  v                    v
  case-stem.md            rubric.md         case-quality.md      case-fit.md
                                                                       |
                                                                       v
                                                    MAST-compatible JSONL + .md sidecar
```

| Stage  | Skill directory                                    | Hands off               |
| ------ | -------------------------------------------------- | ----------------------- |
| 1      | [case-stem-authoring/](case-stem-authoring/)       | `case-stem.md`          |
| 2      | [rubric-design/](rubric-design/) (item-mode adapter) | `rubric.md`             |
| 3      | [case-evaluate/](case-evaluate/)                   | `case-quality.md`       |
| 4      | [case-fit-check/](case-fit-check/)                 | `case-fit.md` + export  |

If `case-evaluate`'s summary verdict says the case needs revision,
control returns to `case-stem-authoring` rather than continuing to
`case-fit-check`.

## Sub-mission skills

### Human annotation

| Skill                                                                    | Hands off                       |
| ------------------------------------------------------------------------ | ------------------------------- |
| [annotation-task-design/](annotation-task-design/)                       | `annotation-task.md`            |
| [annotation-rater-pool/](annotation-rater-pool/)                         | `rater-pool.md`                 |
| [annotation-adjudication/](annotation-adjudication/)                     | `adjudication.md`               |

### Data preparation

| Skill                                                                    | Hands off                       |
| ------------------------------------------------------------------------ | ------------------------------- |
| [data-source-intake/](data-source-intake/)                               | `data-sources.md`               |
| [data-synthesis/](data-synthesis/)                                       | `synthesis-policy.md`           |
| [data-item-shape/](data-item-shape/)                                     | `data-item-shape.md`            |

### Benchmark execution

| Skill                                                                    | Hands off                       |
| ------------------------------------------------------------------------ | ------------------------------- |
| [run-config/](run-config/)                                               | `run-config.md`                 |
| [run-monitor/](run-monitor/)                                             | `run-monitor.md`                |
| [run-inspect/](run-inspect/)                                             | `run-results.json`, `run-results.md` |
| [results-iteration/](results-iteration/)                                 | reviewed revision route and version comparison |

Inspection is universal. [release-writeup/](release-writeup/) is an
optional publication branch after inspection.

## Invariants every skill must uphold

- **One concern per skill.** Do not merge stages. Do not skip
  upstream artifacts.
- **Socratic, not formulaic.** Do not accept "sounds good, proceed"
  as a completion signal. Keep asking until the user's answer is
  defensible.
- **Produce a markdown artifact.** Every stage ends by writing its
  named artifact to the user's benchmark workspace before handing off.
- **MAST-compatible output.** The implementation-plan skill must
  emit a plan that a coding agent can turn into a MAST-submodule-
  compatible benchmark without reshaping.
- **No de-identification or clearance.** Inputs are assumed stripped;
  the dormant signal does not redact, block, certify, or clear.
- **No quality gate.** ARISEKit guides; MAST and the community
  review.
- **Cite upstream artifacts.** Each skill must quote the specific
  claims from the earlier artifacts it relies on, so the user can
  spot stale assumptions.

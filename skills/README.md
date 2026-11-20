# Guided authoring

Use these skills with a coding agent to turn a clinical evaluation idea into
a benchmark plan.

## Start

[Choose a local kit](../docs/kits.md) to start from a named benchmark family.

Open this repository in Claude Code or Codex. Ask the agent to follow
[needs analysis](needs-analysis/SKILL.md) for your idea, then continue through
the stages below. No packaged installer is available yet.

## Stages

| Stage | Purpose |
| --- | --- |
| [Needs analysis](needs-analysis/) | Define the clinical task and evaluation goal |
| [Existing benchmarks](existing-benchmark-search/) | Check whether a suitable benchmark exists |
| [Compliance](compliance-intake/) | Establish permitted data and environments |
| [Data intake](data-intake/) | Describe the inputs and their structure |
| [Scoring design](rubric-design/) | Define how performance will be judged |
| [Study design](study-design/) | Plan evaluation and expert review |
| [Implementation](implementation-plan/) | Produce the benchmark plan and build specification |

Skills ask questions and record decisions in named artifacts. Supported plans can
be built and run with ARISEKit; unsupported sources or scorers need additional code.
Users can stop at a plan or continue to evaluation.

## Operating rules

Keep stages distinct, retain their outputs, and cite the upstream decisions each
stage uses. Skills guide human decisions; they do not certify clinical quality,
de-identify data, or grant data authorization.

See the [workflow reference](REFERENCE.md) for detailed contracts, operating
rules, and additional skills.

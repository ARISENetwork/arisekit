# Getting started

## Local walkthrough

Follow the [root setup instructions](../README.md#run-locally) and open [NOHARMKit](http://localhost:5190/noharm/welcome). Choose the guided walkthrough to work through a prepared case. The [NOHARMKit guide](../toolkits/noharmkit/README.md) describes the project workflow and grading tools.

## Coding-agent authoring

Open the repository in your coding agent. Choose a family in the [kit guide](kits.md), then start the [needs analysis](../skills/needs-analysis/SKILL.md) with your clinical question. The [skill index](../skills/README.md) lists the stages and their outputs. The coding agent uses your configured provider.

## Python evaluation

The contributor environment in the root setup installs the Python tools. To install just the base Python package into a fresh environment, run:

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e .
source .venv/bin/activate
arisekit --help
```

To import an authoring ZIP or inspect a completed run in a local browser, follow the [results workspace guide](../apps/workspace/README.md). The Python wheel includes the interface.

Try the [offline example](../examples/p0-golden-path/README.md). It generates response records and scores using the reference stub. Use synthetic or authorized data and provider routes for your own runs.

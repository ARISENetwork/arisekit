# ARISEKit

ARISEKit is a local toolkit for designing, building, and evaluating medical AI benchmarks. Start with the [kit guide](docs/kits.md) to choose a workflow.

- **NOHARMKit** includes a browser walkthrough with a prepared case, a project editor, and a grading pipeline.
- **Guided authoring** uses the [repository skills](skills/README.md) in your coding agent. The guide identifies the starting point and available evaluation support for each benchmark family.
- **Python** provides dataset loading, inference, checkpoints, scoring, and reporting. The [offline example](examples/p0-golden-path/README.md) builds and scores a two-case benchmark with a reference stub.

## Run locally

From the repository root, with Node.js 22+, Python 3.10+ and uv installed:

```sh
uv sync --project scripts/dev --locked
source scripts/dev/.venv/bin/activate
npm run bootstrap
npm run dev
```

Open the [local kit chooser](http://localhost:5190/kits). The NOHARMKit walkthrough runs without a model key. Model-backed workflows use the provider you configure.

[Getting started](docs/getting-started.md) · [Contributor checks](CONTRIBUTING.md) · [License](LICENSE)

# Contributing to ARISEKit

Follow the [local setup](README.md#run-locally) and activate the contributor Python environment in the same terminal. From the repository root:

```sh
python -m pytest tests -m 'not study and not slow and not live' --strict-markers
npm run build
npm test
(cd toolkits/noharmkit && python -m pytest -c /dev/null --rootdir=. tests)
```

The [offline Python example](examples/p0-golden-path/README.md) and the NOHARMKit walkthrough exercise the installed user paths. Use synthetic fixtures in tests. Preserve the distinction between automated scores and direct human judgments. Keep credentials, participant data, personal projects, and generated results out of commits.

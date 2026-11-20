# P0 golden-path synthetic routing

Two synthetic clinical routing labels that prove the reviewed authoring-to-run contract.

- Benchmark id: `p0-golden-path`
- Version: `0.1.0`
- MAST category: `clinical-reasoning`
- Dataset source: [cases.synthetic.jsonl](<../../examples/p0-golden-path/authoring/cases.synthetic.jsonl>) (SHA-256: `d5ebf0dadd7c0b1f3974ff804862e006614529fa159ab92e1d3bda804c03ebff`)
- Scorer: `arisekit.scorer.exact_match`
- Build specification: [benchmark-build-spec.json](<../../examples/p0-golden-path/authoring/benchmark-build-spec.json>) (SHA-256: `c6ffaa4acacc0691feb6d8be3e9227134431a0e4b0745235ed411a34099bca5c`)

## Planning artifacts

- need-statement: [need-statement.md](<../../examples/p0-golden-path/authoring/need-statement.md>) (SHA-256: `c1b26f4a481744c9e4c37262057c8958e9b9b9095748e2d16d48fa1e0bed17d7`)
- existing-coverage: [existing-coverage.md](<../../examples/p0-golden-path/authoring/existing-coverage.md>) (SHA-256: `f961a61f9fdb72b5cf169019f721a3338577b97436fbb41cded5ae176cefbfd1`)
- compliance-scope: [compliance-scope.md](<../../examples/p0-golden-path/authoring/compliance-scope.md>) (SHA-256: `b1b8ca4265ee76b54dde9dfc9129f85b909f2dd1278abb3a6f3c289067cf1079`)
- data-profile: [data-profile.md](<../../examples/p0-golden-path/authoring/data-profile.md>) (SHA-256: `dd3357a65b7c24f33a2db5b8291e6964f05b5e0d018f4640c8162bd6c2971fae`)
- rubric: [rubric.md](<../../examples/p0-golden-path/authoring/rubric.md>) (SHA-256: `d225dbef0335867b0ce13fbf0c5826c90834875d31d93f29ae5a9eaf018f45d0`)
- study-plan: [study-plan.md](<../../examples/p0-golden-path/authoring/study-plan.md>) (SHA-256: `7ddaf94d3e4835617e1b365c54d6d977b1348894cb46969fa465077a63fce0a0`)
- implementation-plan: [implementation-plan.md](<../../examples/p0-golden-path/authoring/implementation-plan.md>) (SHA-256: `ae07ddb900003ae3e42195c99e5463b1a4b6da9dddabedc883ba4b974d62a944`)

## Planned smoke test

- Model: `stub/reference`
- Limit: `2`
- Trials: `1`

## Run

`arisekit eval p0-golden-path --model stub/reference --limit 2 --trials 1`

The allowed model routes in the build specification are the reviewed execution allowlist from compliance planning. They are not a `ProviderDisclosureAuthorization`.

Structural compatibility only; this does not establish clinical quality, data authorization, privacy compliance, or MAST admission.

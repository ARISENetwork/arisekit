# Autonomous generation rehearsal

This local example runs four independent branches in parallel: SCT-style
specialty generation, CPC-style specialty generation, a novel administrative
text task, and international adaptation. It uses the shared generation
controller, portable packages, existing scorers, and checkpoint resume.

The generator returns illustrative canned outputs. The conditions, reference
counts, diagnoses, and scheduling rules are synthetic fixtures. The results
show software behavior; they are not clinical evidence or evidence of a model's
ability to generate benchmarks. The Swedish wording illustrates a language
transformation, not an actual Swedish healthcare policy.

## Run

From a checkout with ARISEKit installed in the active Python environment:

```sh
python examples/autonomous-generation/rehearsal.py --output /tmp/arisekit-autonomous-rehearsal
```

For the repository's existing virtual environment, use `scripts/dev/.venv/bin/python`.
The script has no live-provider option and requires no credentials. Its
fixture client records zero cost; explicit controller call and cost limits
still apply. Repeating the command with the same output directory reuses the
retained results when the code and inputs remain unchanged.

## Outputs

- `sct/`: one package with an ordinal synthetic reference distribution.
- `cpc/`: one package with two cumulative evidence stages and diagnosis-ranking
  scoring. The stages share one case; they are not independent cases.
- `novel-admin/`: one package with a generated task definition, response
  contract, rubric, and deterministic scorer.
- `international/`: three packages generated independently from the same
  frozen source: language-only, healthcare-setting-only, and combined changes.
- `international-source-baseline/`: the unchanged source as a separate package;
  creating it makes no generator call.
- `rehearsal-summary.json`: package counts, fixed-response scoring checks,
  report paths, costs, and checks that resume makes no new calls.

Each generation directory retains the frozen request plan, runner evidence,
compilation outcomes, and verified packages. The first invocation makes six
fixture calls and writes six generated packages plus the source baseline.

## Use the same APIs with a generator

`specialty_generation_request` supplies the SCT or CPC output contract.
`novel_design_request` supplies a task brief and permitted evidence for a new
text design. `InternationalAdaptationPlan.generation_dataset()` supplies the
three independent adaptation requests, including their source hashes and
allowed evidence IDs. `run_autonomous_generation` dispatches these requests
through the existing runner, compiles outputs, and can perform bounded AI
repair attempts. The shared compiler selects the appropriate adapter.

International compilation preserves a supplied deterministic source scorer.
Generated rubrics remain review artifacts. Missing semantic scoring, translated
answers outside fixed choice labels, invented sources, and unsupported
transformations produce explicit failures. Numeric scoring does not gain
locale-aware parsing from translation.

Evaluate untouched generated candidates independently. Retain any later human
edits as a separate assisted or repair arm. A successful compilation establishes
the package's supported structure and scoring bindings.

The Agentic/FHIR branch is available through
`autonomous_fhir_generation_request` and `compile_autonomous_fhir_candidate`.
It executes proposed reference calls in isolated chart state and derives a
compact JSON answer vector from their outputs. Its integration tests exercise
generation, repair, packaging, tool execution and resume; this script covers
the four branches listed above.

NOHARM's full-draft bridge
uses the shared controller through `run_noharm_generation`, then binds retained
solver responses to the canonical cohort judge. Its response-collection
packages report scoring as pending until canonical results are verified.

For an actual configured generator, the same entry point accepts an existing
ARISEKit model client or model route. For example, with `generator_client`
already configured and these resource limits chosen for the run:

```python
from arisekit import Dataset, novel_design_request, run_autonomous_generation
from arisekit.runner import RunnerConfig

brief = novel_design_request(
    request_id="scheduling-design-1",
    need="Design a benchmark of scheduling priority decisions.",
    evidence={"local-rule": "Synthetic rule: routine requests use the routine route; urgent requests use the urgent route."},
    item_count=3,
)
report = run_autonomous_generation(
    Dataset([brief]), model=generator_client,
    config=RunnerConfig(max_calls=3, max_cost=1.0, max_cost_per_call=0.25),
    output_dir="work/scheduling-design-1", data_classification="synthetic",
    max_repairs=1,
)
```

For a changed brief, model configuration or compiler, use a new output directory.
The report retains every assigned brief, including failed and undispatched
requests. Limits cover generator calls and structural repairs; later solver
and judge runs have their own explicit budgets.

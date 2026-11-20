# Configurable FHIR evaluation environment

Use Python 3.10+ with ARISEKit and Docker Desktop (or a compatible local Docker
engine). The server is HAPI v8.8.0-1, FHIR R4 4.0.1. The registry digest fixes the
multi-platform image; each attempt also records the actual platform image ID.
The [upstream HAPI starter](https://github.com/hapifhir/hapi-fhir-jpaserver-starter)
documents its Docker images and Spring/FHIR configuration.

```sh
pip install -e '.[autonomous,fhir]'
docker pull hapiproject/hapi@sha256:34c86fd5805df77c2b9d9c10538050b16ac3dc244352da0ebe4717f931330775
arisekit fhir generate --brief examples/docker-fhir/brief.json --model openai/gpt-4.1 --output fhir-generation
arisekit fhir validate fhir-generation/packages/outpatient-record-workflows --output fhir-controls
arisekit fhir eval fhir-generation/packages/outpatient-record-workflows --model openai/gpt-4.1 --output fhir-results
```

The web Build view offers the same fields under MedAgentBench / FHIR environment.
Download a brief and use its path in the first command. Set the provider's normal
environment credentials before generation or model execution. `stub/reference`
executes the hidden positive-control actions and makes no provider request.

`brief.json` defines the clinical scope, workflow, supplied evidence/rules,
resource-specific permissions, exact starting chart, scoring criteria, number of
tasks and execution budgets. Every task starts from a separate copy of that chart.
Read/search/create/update/delete tools use actual HTTP against HAPI. An attempt
can access only its patient and allowlisted resource actions. Search uses native
FHIR parameters, validates names against server capabilities and follows bounded
same-server pagination. Each container binds an ephemeral loopback port, uses an
ephemeral in-memory H2 database and is removed on completion or failure.

Generated tasks carry declarative initial/terminal/delta predicates and optional
exact JSON answers. Predicates support exact values, resource counts, existence
and absence; dotted paths and `*` select nested FHIR values. They do not execute
model-supplied code. Distinct successful tool plans can receive the same score.
Unrelated seed resources must remain unchanged. The reference actions declare
which existing resources may be updated/deleted and bound the number of new
resources by type. Recovered search/format errors are diagnostic; permission
violations and exceeded execution limits fail the task.
`reference-candidate.json` is a hand-authored software-control fixture, separate
from autonomous output.

Packages contain cases, their cohort assets, the selected tool schemas and
permissions, the pinned environment, provenance and a strict asset manifest.
`fhir validate` executes each positive plan twice in separate containers, compares
terminal-state hashes, and checks derived wrong-answer/reset-state, extra-write,
unrelated-change and null controls. It returns a failure exit code if those
software checks fail. The standard runner writes response JSONL, per-turn trajectories with initial
and terminal states, provider dispatch journals, costs, timing and run identities.
An interrupted run recreates its server from the last complete checkpoint and
replays only pending intents; it does not reuse another attempt's mutable chart.
Repeat the same command and output path to resume. Keep the package, call journal
and turn journal together. A changed brief or runtime creates a new run identity.
Use the existing `arisekit export-benchmark` / `import-benchmark` commands for a
verified portable distribution (see `--help` for the identity metadata).

An action task whose initial state already satisfies its predicates is rejected.
Actual positive-control execution and negative controls are still required to
check whether generated predicates measure the requested outcome. No clinical
review is inferred from compilation, control success or model performance.

Private clinical data, multiple patients per attempt, arbitrary custom code/tools
and full native MedAgentBench evaluator parity are outside this adapter's current
scope. Existing research protocols and the in-memory v2 package remain unchanged.

Run the actual container checks explicitly:

```sh
ARISEKIT_TEST_DOCKER=1 python -m pytest tests/test_docker_fhir_workflow.py -q
```

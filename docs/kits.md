# Local kits

Open this checkout in your coding agent. Pick a workflow below and give the agent the instruction under **Start an authoring session**. The agent uses the skills and templates included in this repository. Keep your benchmark workspace in a separate directory so its cases and outputs stay outside the toolkit.

| Workflow | Starting task |
| --- | --- |
| [NOHARMKit](../toolkits/noharmkit/README.md) | Open the local browser workflow to build and grade open-ended tasks. Its walkthrough uses a prepared case. |
| SCTKit | Script concordance. A local scoring adapter supports concordance. Provide an authorized distribution and identify whether it comes from experts or a synthetic reference. |
| CPCKit | Diagnostic reasoning. The staged differential adapter accepts diagnosis aliases and uses reciprocal rank. Other variants need their own case and scoring contracts. |
| RCQKit | Open clinical questions. The library includes RCQ item and rating contracts. Identify the reference source and the origin of each judgment. |
| MedAgentKit | Electronic health record tasks. The local FHIR example builds and runs synthetic chart tasks. The original MedAgentBench has its own runtime and access requirements. |
| RadiologyKit | Chest X-ray reporting. The skills support report-task planning. Implement or supply the report scorer before execution. |
| Medical images | Image-based tasks. The multimodal example exercises a local image attachment. Classification and closed-answer questions use task-specific answer profiles. |
| Guided assistant | Custom benchmark. The implementation plan records which data loader and scorer are available and any additional code needed. |

## Start an authoring session

Replace the bracketed text, then paste this into your coding agent:

```text
Read skills/needs-analysis/SKILL.md in this checkout. I want to use [kit]
for [task or clinical setting]. Ask me the first unresolved question.
Save each accepted stage artifact in [my benchmark workspace]. Continue
through skills/README.md until I have a benchmark plan or choose an
existing benchmark. Tell me which parts of the plan I can run locally.
```

The local kit chooser also provides a starter prompt for each family. The [stage guide](../skills/README.md) lists the artifacts the agent will write. For an existing benchmark, use the [public source catalog](../skills/existing-benchmark-search/catalog/public-benchmarks.md) to check data access and execution requirements.

## Local examples

- [Text tasks](../examples/p0-golden-path/README.md)
- [Agentic FHIR tasks](../examples/agentic-fhir-golden-path/README.md)
- [Multimodal tasks](../examples/multimodal-golden-path/README.md)

Each example uses a local reference stub so you can check that the package builds and scores. Running a configured model, cloud service or coding agent follows that provider's connection and billing settings.

# NOHARMKit

Build benchmarks for open-ended clinical queries and cases, with severity-based scoring and clinician review.

## First launch

Follow [Getting started](../../docs/getting-started.md) to run ARISEKit locally. The app includes a guided walkthrough and project workflow instructions.

## How responses are graded

Text-rubric responses are graded the way the NOHARM study grades them. A judge
reads each response against the rubric. Three raters (model or clinician) rate
every rubric item. Each response gets a worst error, taken as the median over
the raters, and an F1 score. When the median says severe, a second model
rechecks the judge in a severe review. A grade is final only when every rater
has rated every item and no severe review is waiting.

New projects use this grading. Older projects keep their earlier scores,
labeled as the previous pipeline, until you upgrade them. The runbook lists the
commands: [Pipeline grading](docs/runbook-e2e-mvp.md#pipeline-grading).

## Technical references

- [API execution and scoring](docs/api-execution.md): model setup, runtime requirements, checkpoints, and recovery.
- [Dataset format](docs/agent-skills.md#dataset-format): case inputs and supported fields.
- [Rubric authoring rules](docs/contracts/rubric-authoring-rules.md): rubric structure and rating rules.
- [Upstream provenance](INTEGRATION.md): source versions and compatibility boundaries.

## Data privacy

Use synthetic data unless your institution approves the data, environment,
coding agent, and provider routes. Model calls can transmit case content;
project files, logs, and backups can contain protected health information (PHI).
Protect viewer access and never commit PHI. You are responsible for data handling;
the toolkit does not verify approval or provide a compliant environment. Authors
and maintainers are not responsible for unauthorized or inappropriate PHI use.

## Terminology

| Term | Meaning |
| --- | --- |
| Case | One task, acceptable solutions, optional errors, and evaluation records |
| Task | Input supplied to the evaluated model |
| Solution | Acceptable answer used to build the rubric, excluded from model inputs |
| Errors | Possible errors and their severity |
| Model response | Output from the evaluated model |

Multiple solutions are alternatives, not cumulative requirements. Bundled
prompts and harm policies are clinical; other domains need their own policies.
Legacy storage keys and flags remain supported; see
[Dataset format](docs/agent-skills.md#dataset-format).

## License

[MIT](LICENSE).

# Review gate for General Medicine Adaptive Consult-10

## Current status

This benchmark is an engineering fixture. It is fully synthetic, unreviewed,
and not clinically validated. It can test loading, tool use, stage transitions,
checkpoint resume, deterministic scoring, and report compilation. It cannot
support a clinical safety claim, a model ranking, or a patient-care decision.

## Engineering controls completed

- Case IDs are opaque.
- Model-visible tool results exclude source IDs, update class, rubric fields,
  and target labels.
- A stage token prevents access to post-update facts before the interim step.
- Scheduled updates declare the topics that they disclose.
- A model can stop after a decisive update instead of asking a redundant
  question.
- Concern and action scoring checks precision as well as recall.
- Tool functions reject malformed, duplicate, oversized, and unknown arrays.
- The scorer handles malformed trajectories without aborting aggregation.
- Patient-facing text is rendered from validated structured actions and must
  be repeated exactly. Free-form medical advice is not evaluated.
- The primary metric is named `structured_contract_completion`; it does not
  claim clinical safety.
- CLI runs use content-addressed manifests, including dataset, prompt, tools,
  executable code, model route, selection, and run configuration.
- An optional AI judge can test rubric concordance, structured-output parsing,
  provenance, cost accounting, checkpoint resume, and positive-versus-negative
  control discrimination.

## AI-judge boundary

Preliminary AI judging is permitted for engineering and rubric-development
feedback. It does not clear this review gate. The judge receives the same
unreviewed draft rubric, so it can reproduce rubric errors. It can also have
model-family bias, prompt sensitivity, correlated failure, and poor calibration.

Do not describe AI-judge agreement as physician agreement or clinical
validation. Keep deterministic metrics and AI-judge metrics separate. Before
using AI judging in a comparative study, clinicians must review the judge
criteria and blinded examples, and the study must measure judge reliability,
failure rates, calibration, and agreement with independent clinician ratings.
An AI-declared pass cannot override a failed deterministic contract.

## Decisions that clinicians must own

Reviewers must define the intended jurisdiction and operational meaning of
each disposition. The definition must state the time window, care venue,
transport expectation, and allowed action combinations.

At least two qualified clinicians must independently review, from stage-masked
facts:

- every initial patient message;
- every pre-update answer;
- every scheduled update;
- every post-update answer;
- the minimum critical information for each stage;
- acceptable interim and final dispositions;
- supported concern codes;
- required and prohibited action codes; and
- whether the scheduled update supports immediate stopping.

A separate clinician should adjudicate disagreements. Review records must
retain reviewer identity, date, source version, decision, rationale, and the
content hash reviewed.

## Evidence work

Replace the current source-anchor list with a claim-level source manifest.
For each source, record:

- title, publisher, URL, and access date;
- publication or review date when available;
- the exact case field that it supports;
- whether it supports a symptom, decision threshold, or action; and
- the jurisdiction in which the recommendation applies.

Source anchors do not validate a case or rubric by themselves.

## Required expansion before model comparison

- Lock a development set and a separate held-out set.
- Use a prespecified sampling frame rather than one case per target concern.
- Cross update class with final disposition so update direction is not a
  shortcut to acuity.
- Add within-condition variants and cases with different useful question
  counts.
- Add demographic, communication, disability, caregiver, access, and health
  literacy variation under a clinician- and fairness-reviewed plan.
- Prespecify the primary endpoint, model versions, prompt, trials, retry
  behavior, stopping rules, and uncertainty method.
- Establish scorer reliability against independent clinician judgments.

Until these steps are complete, report only software-test results and retain
the phrase: **fully synthetic, unreviewed, and not clinically validated**.

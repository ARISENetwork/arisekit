# General Medicine Adaptive Consult-10

`general_medicine_adaptive` is a synthetic engineering pilot for a multi-turn general-medicine benchmark. It tests whether a model can select high-value history topics, submit an interim assessment, incorporate a controlled new fact, and produce a structured tele-triage disposition under a fixed question budget.

## Status and permitted use

Every item is fully synthetic, unreviewed, and not clinically validated. The cases are not patient data, clinical guidance, a diagnostic system, or evidence that any model is safe for health care. No response produced from these items may be shown to or used for a real patient.

The source anchors identify public clinical information used to bound the synthetic drafts. They do not make the case facts, rubric, intended disposition, or action codes clinically approved. Named clinicians must review and lock those fields before any result is described as more than an engineering smoke test.

This directory contains:

- `data/items.synthetic.v1.jsonl`: ten `BenchmarkItem` records.
- `prompts/system.txt`: the solver protocol.
- `environment.py`: deterministic patient tools over the hidden synthetic fact banks.
- `scorer.py`: deterministic trajectory scoring.
- `preliminary_judge.py`: resumable, cost-capped AI judging for pipeline tests.
- `validation.py`: load-time structural and clinical-status invariants.
- `REVIEW_GATE.md`: clinician-owned work required before model comparison.
- `__init__.py`: the benchmark `build()` factory.

## Scope

- Canonical specialty: `primary-internal-medicine`
- Setting: synthetic adult first-contact tele-triage
- Language: English
- Modality: structured text dialogue
- Case count: 10
- Attachments: none
- Exclusions: pediatrics, pregnancy, psychiatric crisis, procedures, physical examination, EHR actions, prescribing, medication doses, and real patient care

The case mix contains four draft emergency targets, three draft same-day targets, one draft self-care target, and two draft routine targets. This deliberately small and acuity-heavy set is useful for software checks only. It is not representative or powered for model comparison.

## Run the engineering smoke test

Use a model route that supports structured tool calls:

```sh
uv run arisekit \
  --results-dir results \
  eval general_medicine_adaptive \
  --model openai/gpt-4o-mini \
  --limit 2 \
  --trials 1 \
  --threads 1
```

Each CLI run creates a content-addressed manifest. Final trajectories,
incremental turn journals, and score CSVs are namespaced by that manifest
digest. Restarting the same run resumes without repeating completed patient
topics or tool calls. Changing an item, prompt, tool schema, scorer, model
route, or run configuration produces a different digest instead of reusing
stale rows.

## Interaction contract

The environment exposes four structured tools. Every call includes the exact,
opaque case ID:

1. `ask_patient(case_id, topic)`
2. `submit_interim(case_id, disposition)`
3. `ask_patient_after_update(case_id, stage_token, topic)`
4. `finish_consult(case_id, stage_token, disposition, concern_codes, action_codes, evidence_topics)`

The model requests exactly two unique pre-update topics, calls
`submit_interim`, and receives both the scheduled update and an opaque stage
token. Post-update facts require that token. The model may finish immediately
after a decisive update or request up to three unique follow-up topics. Calls
are sequential, with one tool call per model turn. `finish_consult` renders the
patient-facing message from the validated disposition and actions; the model
must repeat that message exactly.

The topic vocabulary is:

- `timing_course`
- `location_quality_severity`
- `triggers_relief`
- `associated_general`
- `cardiopulmonary_red_flags`
- `neurologic_red_flags`
- `gastrointestinal_red_flags`
- `genitourinary_red_flags`
- `relevant_history_risk`
- `medications_allergies`
- `objective_measurements`
- `functional_status`

## Item shape

Each JSONL row is a valid `BenchmarkItem`:

- `prompt` is the initial synthetic patient message.
- `metadata.patient_simulator.fact_bank` contains deterministic answers keyed by topic.
- `metadata.patient_simulator.scheduled_update` contains the controlled
  post-interim disclosure and the topics it discloses.
- `ground_truth` contains weighted pre- and post-update topics, acceptable interim dispositions, a final disposition, accepted concern codes, and required and prohibited action codes.
- `attachments` is empty.

`status: synthetic_draft`, `synthetic: true`, and `clinically_validated: false` are load-bearing fields. They must not be represented as clinical review or validation.

## Deterministic scoring

`AdaptiveConsultScorer` uses only the recorded structured tool trajectory and
item rubric. The primary metric is `structured_contract_completion`. The name
is deliberate: this unreviewed fixture does not establish clinical safety. A
trajectory passes only if it follows the stage-gated tool order and budgets,
obtains all critical topics, submits the draft target disposition, selects
only supported concerns and required actions, cites disclosed evidence, and
repeats the canonical patient message exactly.

Secondary metrics report pre-update, post-update, weighted, and critical
information recall; duplicate-free topic selection; update and protocol
adherence; exact disposition; under- and over-triage avoidance; concern and
action recall and precision; prohibited-action avoidance; supported evidence;
and canonical message adherence. The primary metric is also stratified by
update class and target disposition. Trials are reduced within case before
cases are aggregated. This ten-case fixture should report point estimates
only.

## Preliminary AI judge

The optional AI judge checks whether completed trajectories are internally
concordant with the unreviewed draft rubric. It does not decide whether that
rubric is medically correct. Its outputs must retain the label **preliminary,
automated, and not clinically validated**.

First verify the judge path with one contract-concordant control and one
adversarial control:

```sh
uv run python -m benchmarks.general_medicine_adaptive.preliminary_judge \
  --fixture \
  --judge-model gpt-4o-mini-2024-07-18 \
  --results-dir results/preliminary-ai-judge-smoke \
  --max-cost 0.10 \
  --max-calls 2 \
  --max-cost-per-call 0.05
```

Then judge a completed general-medicine raw checkpoint:

```sh
uv run python -m benchmarks.general_medicine_adaptive.preliminary_judge \
  --raw results/raw/general-medicine-adaptive/<manifest>/<model>.jsonl \
  --judge-model gpt-4o-mini-2024-07-18 \
  --results-dir results \
  --max-cost 1.00 \
  --max-calls 10 \
  --max-cost-per-call 0.10
```

The judge uses strict JSON output and records five anchored dimensions:
evidence grounding, temporal reasoning, triage alignment, action alignment,
and interaction efficiency. It persists the exact judge inputs, raw provider
responses, parsed judgments, score CSV, provider response IDs, token use,
costs, and a content-addressed run manifest. Repeating an identical command
resumes without another provider call.

The reported preliminary pass is a hybrid gate. The AI judge can add
qualitative feedback, but it cannot override a failed deterministic contract.
Reports keep the AI-declared pass rate and the hybrid pass rate separate. This
rule was added after a live smoke test found that a same-family judge gave a
5/5 review to a trajectory with a machine-detectable interim-disposition and
evidence mismatch.

The default is a pinned small-model snapshot for a low-cost smoke test. A real
study should prespecify and validate a multi-judge design, measure agreement
against clinicians, and keep model families independent where practical.

## Clinical source anchors

The cases cite authoritative public pages in their metadata, including:

- [Heart attack](https://medlineplus.gov/heartattack.html), MedlinePlus, U.S. National Library of Medicine
- [Subarachnoid hemorrhage](https://medlineplus.gov/ency/article/000701.htm), MedlinePlus
- [Pulmonary embolism](https://medlineplus.gov/pulmonaryembolism.html), MedlinePlus
- [Cauda equina syndrome](https://www.nbt.nhs.uk/our-services/a-z-services/neurosurgery/neurosurgery-patient-information/same-day-emergency-clinic-sdec-cauda-equina-syndrome-sec), North Bristol NHS Trust
- [Kidney infection (pyelonephritis)](https://www.niddk.nih.gov/health-information/urologic-diseases/kidney-infection-pyelonephritis/symptoms-causes), National Institute of Diabetes and Digestive and Kidney Diseases
- [Appendicitis symptoms and causes](https://www.niddk.nih.gov/health-information/digestive-diseases/appendicitis/symptoms-causes), NIDDK
- [Community-acquired pneumonia in adults](https://medlineplus.gov/ency/article/000145.htm), MedlinePlus
- [Common cold](https://medlineplus.gov/commoncold.html), MedlinePlus
- [Gastroesophageal reflux disease](https://medlineplus.gov/gerd.html), MedlinePlus
- [Balance disorders](https://www.nidcd.nih.gov/health/balance-disorders), National Institute on Deafness and Other Communication Disorders

These anchors support author review; they are not a substitute for review.

## Existing-benchmark overlap

This fixture must not be presented as a new clinical-evaluation concept without a formal current search. [HealthBench](https://openai.com/index/healthbench/) already evaluates responses to multi-turn health conversations, although its evaluated model responds to the last user message rather than conducting this structured adaptive interview. [MedDialogRubrics](https://arxiv.org/abs/2601.03023) directly overlaps multi-turn medical information gathering with a patient agent. [ThReadMed-QA](https://arxiv.org/abs/2603.11281) evaluates authentic patient-physician threads, and [ClinicalMC](https://arxiv.org/abs/2606.03157) evaluates evolving multi-course clinical decisions.

The current rationale for this work is narrower: provide ARISEKit with a deterministic, inspectable dialogue fixture and scoring contract. It is not a novelty claim.

## Required review before any live comparison

At minimum, two qualified clinicians should independently review every initial message, fact-bank answer, scheduled update, topic weight, concern code, disposition, and action code. A third clinician should adjudicate disagreement. Review records should cite source IDs and timestamps, and any clinical edit should invalidate downstream locks.

Until that work occurs, retain the exact description: **fully synthetic, unreviewed, and not clinically validated**.

Engineering hardening does not resolve the clinical-review gap. The next
content gate is masked review of each stage by at least two clinicians,
adjudication of disagreement, and a clinician-owned definition of every
disposition and action code. A comparative model run before that gate remains
out of scope.

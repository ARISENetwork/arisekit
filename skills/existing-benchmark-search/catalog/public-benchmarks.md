# Public medical AI benchmarks - curated catalog

This catalog supports `arisekit/existing-benchmark-search`. Use it to find
plausible coverage, then verify the benchmark against the user's population,
modality, outcome, and access constraints before recommending it.

_Last full review: 2026-09-02._

## How to use this catalog

- `member` means that the benchmark appears on the official
  [MAST benchmark roster](https://www.arise-ai.org/mast/benchmarks). `external`
  means that no MAST membership is claimed.
- `Public` means that at least the named code or data artifact can be obtained
  from the linked source. It does not mean that every test label, licensed
  case, model API, judge, or compute resource is free or unrestricted.
- This repository has one checked-in public-benchmark adapter: the validated
  First Do NOHARM launcher documented below. Other upstream run kits are not
  ARISEKit adapters. For those entries, link the upstream source when writing
  `existing-coverage.md`; do not invent a local command.
- Access and leaderboard rules change. Recheck the linked source before a
  `stop` recommendation, especially for gated or licensed data.

## MAST benchmarks

The first five entries are the names required by this skill. PhysicianBench
and Multimodal Images are also included because the official MAST roster lists
them as current members.

| Name and official source | MAST status | Modality and coverage | Scoring pattern | Access notes | ARISEKit support | Last verified |
| --- | --- | --- | --- | --- | --- | --- |
| [First Do NOHARM v2](https://github.com/ARISENetwork/mast/tree/main/benchmarks/donoharm) ([paper](https://arxiv.org/abs/2512.01241)) | member | Free-text management plans from generalist-to-specialist consultations; safety, completeness, and robustness across clinical variants. The open kit has 30 base cases and 330 variants. | Two-stage Gemini rubric judge; headline severity-weighted `F1_weighted` with weighted precision/recall, `Severe_rate`, resilience, and confidence intervals. | Public open subset and run kit. Model inference and Gemini judge keys are required and incur cost. The full study benchmark is larger than the open subset. | Checked-in validated launcher: `arisekit public-benchmark noharm --source <NOHARM_ROOT> inspect`, then the documented [`run` and `score` handoff](../../../benchmarks/noharm_reference/README.md). It delegates scoring to the official cohort-level judge; it is not `arisekit eval`. | 2026-09-02 |
| [SCT-Bench / Script Concordance Test](https://github.com/ARISENetwork/mast/tree/main/benchmarks/sct) ([paper](https://ai.nejm.org/doi/full/10.1056/AIdbp2500120)) | member | Text scenarios with a hypothesis, new clinical information, and a rating from -2 to +2; probabilistic diagnostic and treatment reasoning under uncertainty. | Deterministic concordance with expert-panel response distributions; headline `sct_score` from 0 to 1 with an item-bootstrap confidence interval. | Public 174-item open subset and run kit; the published multicenter benchmark is larger. Model inference access is still required. | No checked-in adapter; use the [official MAST kit](https://github.com/ARISENetwork/mast/tree/main/benchmarks/sct). | 2026-09-02 |
| [MedAgentBench v2](https://github.com/ARISENetwork/medagentbenchv2) ([paper](https://psb.stanford.edu/psb-online/proceedings/psb26/chen_eric.pdf)) | member | Agentic, multi-step tasks against a FHIR-compliant simulated EHR; 300 clinically driven tasks test retrieval, conditional reasoning, and clinical actions. | Task success/accuracy from the benchmark evaluators, with overall and per-task results. | Public code and task file. Requires Docker, a FHIR server, and supported model credentials; the official MAST wrapper also refers to infrastructure outside this repository. | No checked-in adapter; use the [official ARISE fork](https://github.com/ARISENetwork/medagentbenchv2). | 2026-09-02 |
| [ReXrank Mini](https://www.arise-ai.org/mast/benchmarks) ([full ReXrank source](https://github.com/rajpurkarlab/ReXrank), [project site](https://rexrank.ai/)) | member | Multimodal chest radiography: report generation and visual question answering. MAST identifies Mini as a curated subset of full ReXrank. | MAST says Mini uses the ReXrank harness. Full ReXrank reports multiple task metrics; do not reduce Mini to a single `GREEN` score unless the current harness says so. | Public ReXrank code and project documentation; official leaderboard evaluation uses held-out data and the MAST-curated subset. Confirm dataset and submission terms with ReXrank. | No checked-in adapter; use the [ReXrank source](https://github.com/rajpurkarlab/ReXrank) and MAST roster. | 2026-09-02 |
| [CPC-Bench](https://cpcbench.com/) ([paper](https://arxiv.org/abs/2509.12194)) | member | Text and images from 7,102 licensed NEJM Clinicopathological Conference cases; 10 tasks cover differential diagnosis, testing, evidence retrieval, clinical QA, reasoning, and image interpretation. | Task-specific leaderboard measures include `DDx@1`, `DDx@10`, testing-plan, literature-search, QA/VQA, visual differential, Image Challenge, and an average. | Public site and leaderboard. The cases are licensed from NEJM; no standalone public dataset or run harness was verified on the official site. | No checked-in adapter; use the [official project site](https://cpcbench.com/). | 2026-09-02 |
| [PhysicianBench](https://github.com/ARISENetwork/PhysicianBench) ([paper](https://arxiv.org/abs/2605.02240)) | member | Agentic FHIR EHR work: 100 long-horizon physician tasks, 670 checkpoints, and 21 specialties using real patient records. | Execution-based pytest verifiers; task success is reported as `pass@1`, with repeated-run measures available. | Public code. The preloaded FHIR Docker image is distributed through Stanford Redivis and requires its access terms; Docker and model credentials are required. | No checked-in adapter; use the [official ARISE fork](https://github.com/ARISENetwork/PhysicianBench). | 2026-09-02 |
| [Multimodal Images](https://www.arise-ai.org/mast/benchmarks) ([MAST source roster](https://github.com/ARISENetwork/mast)) | member | Clinical and dermoscopic skin-lesion assessment using DDI and MRA-MIDAS, both with histopathologic confirmation. | MAST leaderboard evaluation. The public MAST page does not document a standalone metric implementation or run kit for this component. | Dataset access is controlled by the DDI and MRA-MIDAS source terms; image-capable model access is required. | No checked-in adapter; use the [official MAST roster](https://www.arise-ai.org/mast/benchmarks) and linked dataset sources. | 2026-09-02 |

## Other major benchmarks

These entries are external to MAST. They are selected for broad coverage across
patient-facing dialogue, clinician work, EHRs, medical exams, literature QA,
and medical images.

| Name and official source | MAST status | Modality and coverage | Scoring pattern | Access notes | ARISEKit support | Last verified |
| --- | --- | --- | --- | --- | --- | --- |
| [HealthBench](https://openai.com/index/healthbench/) ([data](https://huggingface.co/datasets/openai/healthbench), [reference evaluator](https://github.com/openai/simple-evals/blob/main/healthbench_eval.py)) | external | 5,000 multilingual, multi-turn conversations for patient- and clinician-facing health scenarios, with 48,562 physician-written rubric criteria. | A model grader evaluates weighted criteria; the overall score is points earned divided by available points, with theme and behavior-axis views. The reference evaluator uses a judge model. | Public MIT-licensed data and evaluation code. Requires candidate-model inference and judge-model access; the authors ask users not to republish examples to limit contamination. | No checked-in adapter; use the [official data and evaluator](https://github.com/openai/simple-evals/blob/main/healthbench_eval.py). | 2026-09-02 |
| [HealthBench Professional](https://huggingface.co/datasets/openai/healthbench-professional) ([paper](https://arxiv.org/abs/2604.27470)) | external | 525 public text tasks based on work clinicians bring to AI systems, labeled as consultation, writing, or research across specialties. | Weighted physician-authored rubrics with model grading. OpenAI retains a small private set and states that its exact internal evaluator is not released; the HealthBench evaluator offers an unofficial compatible path. | Public MIT-licensed 525-row set, plus a private held-out set. Candidate and judge inference are required. | No checked-in adapter; use the [official dataset card](https://huggingface.co/datasets/openai/healthbench-professional). | 2026-09-02 |
| [MedHELM](https://github.com/stanford-crfm/helm/blob/main/docs/medhelm.md) ([paper](https://arxiv.org/abs/2505.23802)) | external | A HELM suite organized into 5 clinician-validated categories, 22 subcategories, and 121 tasks spanning decision support, documentation, communication, research, and workflow. | Scenario-specific metrics and, for some generative scenarios, model-judge or jury evaluation; there is no single universal MedHELM score to substitute for the scenario results. | Open-source HELM framework. Access is mixed: public configurations coexist with gated and private scenarios; provider credentials and substantial compute can also be required. | No checked-in adapter; use the [official HELM documentation](https://github.com/stanford-crfm/helm/blob/main/docs/medhelm.md). | 2026-09-02 |
| [MedQA](https://github.com/jind11/MedQA) ([paper](https://arxiv.org/abs/2009.13081)) | external | Text multiple-choice questions from professional medical board exams, including English USMLE-style and Chinese exam sets; measures medical knowledge and exam reasoning. | Exact selected-option accuracy. | Public author repository with data download links and MIT-licensed repository code. Review the terms of the underlying exam and textbook content for the intended use. | No checked-in adapter; use the [official author repository](https://github.com/jind11/MedQA). | 2026-09-02 |
| [MedAlign](https://github.com/som-shahlab/medalign/) ([paper](https://arxiv.org/abs/2308.14089)) | external | 983 clinician-written instructions grounded in 275 longitudinal EHRs, with 303 reference responses; covers timeline understanding, clinical reasoning, and multi-document synthesis. | The original benchmark uses clinician preference/ranking for response quality; automated NLG and judge-based analyses are secondary and should not be treated as exact-answer scoring. | Gated Redivis application, HIPAA CITI training, DUA, and secure storage. Test-only; no redistribution, and no transmission to non-HIPAA-compliant commercial APIs. | No checked-in adapter; use the [official repository and access instructions](https://github.com/som-shahlab/medalign/). | 2026-09-02 |
| [PubMedQA](https://github.com/pubmedqa/pubmedqa) ([paper](https://aclanthology.org/D19-1259/)) | external | Text biomedical research-question answering over PubMed abstracts with `yes`, `no`, or `maybe` labels; includes 1,000 expert-labeled examples plus larger artificial and unlabeled sets. | Three-way answer accuracy in the original benchmark. | Public data and code under the repository's MIT license; inference compute is required. | No checked-in adapter; use the [official author repository](https://github.com/pubmedqa/pubmedqa). | 2026-09-02 |
| [MedMCQA](https://github.com/medmcqa/medmcqa) ([paper](https://proceedings.mlr.press/v174/pal22a.html)) | external | More than 194,000 text multiple-choice questions from Indian medical entrance exams across 21 subjects, often with explanations. | Exact selected-option accuracy; the official held-out test labels are hidden and leaderboard evaluation uses a submission. | Public repository and train/development data under MIT; official test scoring requires the benchmark submission process. Review source-question terms before reuse. | No checked-in adapter; use the [official author repository](https://github.com/medmcqa/medmcqa). | 2026-09-02 |
| [MedXpertQA](https://github.com/TsinghuaC3I/MedXpertQA) ([paper](https://arxiv.org/abs/2501.18362)) | external | 4,460 expert-level questions across 17 specialties, with separate text and multimodal medical-exam subsets. | Exact selected-option accuracy, reported by subset using the supplied evaluator. | Public MIT-licensed repository, dataset link, and evaluation code. Multimodal evaluation requires an image-capable model and provider credentials or local inference. | No checked-in adapter; use the [official author repository](https://github.com/TsinghuaC3I/MedXpertQA). | 2026-09-02 |
| [Diverse Dermatology Images (DDI)](https://ddi-dataset.github.io/index.html) ([paper](https://arxiv.org/abs/2203.08807), [Stanford AIMI record](https://aimi.stanford.edu/datasets/ddi-diverse-dermatology-images)) | external | 656 pathologically confirmed clinical skin images from 570 patients across Fitzpatrick I-VI; supports benign-versus-malignant assessment and subgroup performance analysis. | The reference work reports malignancy ROC-AUC overall and across skin-tone and disease-frequency groups; official model and evaluation code is linked from the project page. | Individual registration and Stanford research-use agreement; personal, non-commercial research only, no redistribution, and no clinical use. | No checked-in adapter; use the [official DDI project](https://ddi-dataset.github.io/index.html). | 2026-09-02 |

## Vendor eval claims that are not reusable public benchmarks

- [Doximity Ask](https://technology.doximity.com/articles/doximity-ask) is a
  system, not a catalog benchmark. Doximity describes an internal core
  evaluation set of nearly 2,000 scenarios, but the official page does not
  release the data or evaluator. Do not present it as a runnable match.
- [OpenEvidence](https://www.openevidence.com/) is a clinical information
  product. This review found no standalone public benchmark dataset and harness
  on its official project pages. Do not convert product claims into a catalog
  candidate without a primary public source.

## Maintenance

- Review the catalog at least quarterly and update every `Last verified` field.
- Use primary sources: official benchmark repositories, official project or
  dataset pages, and papers from the benchmark authors.
- Check MAST membership against the official roster; do not infer membership
  from an author, model result, repository fork, or topical overlap.
- Before adding a run command or import, confirm that the adapter and entry
  point are checked into this repository and test the exact snippet.
- If an entry has not been verified for six months, call that out in the
  generated coverage report and recheck access before recommending it.
- When removing an entry, leave a dated tombstone with the reason.

# Existing-benchmark coverage

_Author:_ P0 golden-path fixture owner  
_Date:_ 2026-09-02  
_Produced by:_ `arisekit/existing-benchmark-search`  
_Upstream:_ [`need-statement.md`](need-statement.md)  
_Status:_ accepted

## Need summary (paraphrased)

ARISEKit maintainers need a public, synthetic, two-item fixture that proves the repository's accepted authoring artifacts can drive strict scaffolding, local smoke execution, and verifiable result inspection. Clinical-content coverage and clinical performance are outside this need.

## Sources queried

| Source | Last updated |
| --- | --- |
| [ARISEKit public-benchmark catalog](https://github.com/ARISENetwork/arisekit/blob/main/skills/existing-benchmark-search/catalog/public-benchmarks.md) | 2026-09-02 - reviewed; its public clinical-content benchmarks do not replace this repository-contract fixture |
| [MAST benchmark roster](https://www.arise-ai.org/mast/benchmarks) | 2026-09-02 - reviewed for member benchmarks that might cover the need |
| [HealthBench official overview](https://openai.com/index/healthbench/) | 2026-09-02 - reviewed with its public data and evaluator handoff |

## Candidate matches

### 1. HealthBench

- Home: https://openai.com/index/healthbench/
- MAST status: external.
- Modality: multilingual, multi-turn clinical text conversations.
- Scoring style: physician-authored weighted rubrics evaluated by a model grader.
- Access: public MIT-licensed data and evaluation code; candidate-model and judge-model access are required.
- Confidence: low
- Rationale: HealthBench measures clinical conversation quality, but it does not prove that this repository's accepted authoring artifacts can drive strict scaffolding, local smoke execution, and verifiable result inspection for the required synthetic fixture.
- ARISEKit support: No checked-in adapter. Use the official upstream evaluator at https://github.com/openai/simple-evals/blob/main/healthbench_eval.py.

### 2. First Do NOHARM v2

- Home: https://github.com/ARISENetwork/mast/tree/main/benchmarks/donoharm
- MAST status: member.
- Modality: free-text clinical management plans.
- Scoring style: two-stage rubric judge with severity-weighted precision, recall, and F1.
- Access: public 30-case open subset and run kit; model inference and Gemini judge credentials are required.
- Confidence: low
- Rationale: First Do NOHARM measures clinical management safety and completeness, but it does not cover the repository-specific authoring, scaffolding, smoke-execution, and result-inspection contract required by this synthetic fixture.
- Upstream and checked-in launcher handoff:

```text
git clone https://github.com/ARISENetwork/mast.git ../mast
arisekit public-benchmark noharm --source ../mast/benchmarks/donoharm inspect
```

## Recommendation

`continue`

Reason:

The optional existing-benchmark exit was considered. HealthBench and First Do NOHARM evaluate clinical model behavior, but neither provides the requested checked-in end-to-end proof of ARISEKit's authoring-to-results repository contract.

## User decision

- Chose to: continue building.
- Reason (verbatim): "Ship one P0 golden path."

## Next stage

- If `stop`: N/A because no match was accepted.
- Otherwise: `arisekit/compliance-intake`.

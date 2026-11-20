# MAST benchmark recognition reference

Use this reference to recognize the public benchmark families in the [public catalog](public-benchmarks.md). Before executing a benchmark, check its release, access requirements and adapter support.

## Recognition in every authoring stage

Read this reference before responding to a named benchmark, including the
first needs-analysis turn. Match aliases without regard to capitalization or
hyphens. In a medical benchmark conversation, recognize SCT, CPC, NOHARM,
MedAgentBench, and ReXrank immediately; do not ask the user to define a known
acronym. State the recognized task briefly, then ask about the specific
specialty, population, setting, or intended change that is still missing.
Use the prior conversation: do not ask again for women's health if already given.

An adaptation request is already a useful brief. For example, “a noharm version
for womens health” means adapting First Do NOHARM's management-plan safety
assessment to women's health. Start with that interpretation and ask which
women's health setting or safety problem to cover. Do not restart with “what
benchmark do you have in mind?” or require the author to teach the base format.

If a later message says “SCT” after choosing NOHARM, acknowledge SCT as the
Script Concordance Test and ask whether to switch to SCT or combine the two
approaches. Do not silently replace the earlier choice. If a name has several
variants, recognize the family and clarify the variant only when it matters.
Unknown acronyms still need clarification; do not force them into this list.

Recognizing a design does not authorize reading private data. For planning,
use this metadata immediately without requiring the sibling checkout or a
network search. For execution, verify the selected source, access, and adapter.
Keep private/full datasets distinct from public subsets. Do not invent run
commands, expert distributions, or claims that a specialty adaptation already
exists. In coverage search, compare the requested adaptation with the base
benchmark; shared format alone does not mean the specialty need is covered.

## Core families

| Name and aliases | Upstream directories | Task and scoring pattern |
| --- | --- | --- |
| First Do NOHARM; NOHARM; no harm; do no harm; donoharm | `benchmarks/donoharm`, `benchmarks/noharm` | Free-text clinical management plans, evaluated for harmful actions and omitted necessary actions using action rubrics and staged judging. Preserve severity weighting and robustness across variants. Inspect the selected release before choosing its exact scoring contract. |
| SCT-Bench; SCT; Script Concordance Test | `benchmarks/sct` | Clinical scenario, diagnostic or treatment hypothesis, and new information; rate the effect from -2 to +2. Score concordance against an expert-panel response distribution. Synthetic reference distributions must remain labeled separately from expert judgments. |
| CPC-Bench; CPC; cpcbench | `benchmarks/cpcbench` and `benchmarks/cpcbench-*` | NEJM clinicopathological-case reasoning. Variants: `cpcbench-ddx` (differential diagnosis), `cpcbench-management` (differential plus testing plan), `cpcbench-qa` (text multiple choice), and `cpcbench-vqa` (image multiple choice). Ask which variant if the request does not settle it. |
| MedAgentBench; Med Agent Bench | `benchmarks/medagentbench` | Multi-step EHR tasks through FHIR tools, evaluated for task completion with pass-at-one scoring. |
| ReXrank; ReXrank Mini | `benchmarks/rexrank` | Chest X-ray images to radiology reports, with report-quality judging. Mini denotes a subset; do not equate it with the full collection. |

For public availability and supported ARISEKit run handoffs, also read
[the public benchmark catalog](public-benchmarks.md).

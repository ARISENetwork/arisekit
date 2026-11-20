# NOHARMKit project charter

Build reviewable severity-weighted benchmarks from supplied tasks and solutions,
preserving evidence through each transformation. [Terminology](../README.md#terminology)
applies across domains; bundled prompts, harm rules, and this clinical policy
remain clinical. Other domains require their own policies.

## Clinical authority

- Initial ratings are optional, revisable silver references. Authorship and authority are separate: automated, human, hybrid, or consensus authority must be declared. Human authorship alone is not consensus; clinical acceptance needs declared clinician review, and gold claims need independent adjudication.
- Approval binds to exact content. Saving records a review action, not validation. Never fabricate approval. Preserve full-case context, original sources, edits, unresolved findings, and independent reviewer contributions. Rubric, judgment, and score authority remain distinct.
- Account for each supplied criterion once in provenance, allowing explicit merges, splits, refinement, regrading, additions, and retirement. Preserve original wording/ratings. Favor clinical coherence over matching source counts; reconsider harm when interactions or alternatives change.

## Clinical representation

Represent acceptable alternatives, required combinations, timing, dependencies,
safeguards, omissions, and commissions in full patient context. One preferred
solution must not become the only acceptable plan. Follow the
[rubric contract](contracts/answer-table-rubric-v1.md) and
[harm guidance](contracts/harm-scale-current.md).

## Evidence and reporting

- Judges map quoted evidence; deterministic code scores. Do not change grades, weights, denominators, or clinical rules during judging. Keep adequacy, safety events, global quality, coverage, and authority separate.
- Preserve raw outputs, reviewer submissions, disagreement, and failures. Unresolved, quarantined, stale, or incompletely reviewed records cannot be reported complete or publishable. Model agreement is not clinical validation.
- Freeze comparisons, weights, denominators, and reference authority before examining results. Separate mapping from scoring errors and report harmful/lenient discrepancies separately.
- Descriptive reports imply no confidence interval, clinical agreement, or external validation. Additional statistics must name methods, source records, and limitations. Mapping/scoring do not validate global quality or release acceptance.

## Provenance and change control

Bind task, solution, criteria, code, prompt, schema, model, configuration, rubric,
response, judgment, score, trials, and model scope. Changed sources need new
identities, not reused caches or approvals. Preserve completed evidence;
invalidate only dependent artifacts. Document validation-set exposure and verify
rubric fidelity, judge fidelity, deterministic scoring, and whole-system behavior
separately. A receipt alone does not prove completion.

The toolkit imposes no research campaign, budget, or experiment registry. The
demo is synthetic. Surface conflicts between policy and implementation.

## Review interface

Show full Task and Solution before isolated judgments. Keep domain concepts
primary and transformations inspectable. Changing human, LLM, hybrid, imported,
or deterministic actors must preserve responsibilities. Desktop controls must be
keyboard accessible, visibly focused, and understandable without color alone.

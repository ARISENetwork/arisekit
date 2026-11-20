# Data item shape

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/data-item-shape`
_Batch ID:_ <slug or uuid>
_Emit version:_ <v1, v2, ...>
_Upstream:_ [`data-sources.md`](data-sources.md) (if applicable),
[`synthesis-policy.md`](synthesis-policy.md) (if applicable)

## Target benchmark

- **Selected target.** <CPC-Bench | NOHARM | SCT-Bench | ReXrank | MedAgentBench | builder-draft:<title>>
- **Prompt shape.** <string | list[dict] | list[dict] with image content>
- **Ground-truth shape.** <expert panel dict | structured rubric | trajectory reference | reference report | other>
- **Attachments required?** <none | one image per item | other>

## Prompt template

```
<For string-prompt benchmarks, the template literal with {field}
placeholders.>
```

```json
[
  { "role": "system", "content": "<system prompt with {field} placeholders>" },
  { "role": "user", "content": "<user content with {field} placeholders>" }
]
```

## Field mappings

| BenchmarkItem slot | Source | Staged field | Notes |
| ------------------ | ------ | ------------ | ----- |
| prompt | <upload-1 / synthesis> | <field> | <interpolated into template> |
| ground_truth.<key> | <upload-1 / synthesis / needs-annotation> | <field or null> | <coercion notes> |
| metadata.specialty | <upload-1 / synthesis / fixed> | <field or value> | |
| metadata.source | fixed | <"fhir-bundle:provider-a" / "synthesis" / ...> | |
| metadata.phi_status | <upload-1.phiPosture> | derived | |
| metadata.label_status | derived | <source-labeled / synthesis-labeled / needs-annotation> | |
| metadata.batch_id | fixed | <batch ID> | |
| metadata.data_pipeline_version | fixed | <repo VERSION> | |
| attachments[0] | <upload-1> | <field> | <gs://... resolved at emit> |

## ID strategy

- [ ] Deterministic (default): `sha256(source_path + row_index)[:12]` prefixed by `batch-{batchId}`
- [ ] Sequential: `batch-{batchId}-row-{n}`

**Justification (if sequential).** <One sentence.>

## Dry-run preview

_The first three drafts as they would be emitted to JSONL. Confirm
each before triggering the full emit._

```json
{
  "id": "batch-<id>-<hash-or-row>",
  "prompt": "<resolved string or message list>",
  "ground_truth": { },
  "metadata": {
    "benchmark": "<target>",
    "specialty": "<value>",
    "source": "<value>",
    "synthesis_policy": "<digest or null>",
    "phi_status": "<value>",
    "label_status": "<value>",
    "data_pipeline_version": "<value>",
    "batch_id": "<value>"
  },
  "attachments": []
}
```

```json
<second draft>
```

```json
<third draft>
```

## Emit results

| Metric | Value |
| ------ | ----- |
| Items emitted | <integer> |
| Items labeled at emit | <integer> |
| Items needing annotation | <integer> |
| JSONL path | `gs://<bucket>/sessions/<uid>/dataPipeline/<batchId>/items-v<n>.jsonl` |
| Manifest path | `gs://<bucket>/sessions/<uid>/dataPipeline/<batchId>/manifest.md` |

## Annotation handoff

- [ ] All items labeled at emit — no handoff needed.
- [ ] Handoff triggered — `needsLabeling` list written to Firestore.

**Items pending annotation.** <integer; see batch doc for full list>

**Re-emit plan.** <On label return, run `pipeline_merge_labels` and bump to `items-v<n+1>.jsonl`.>

## Notes for the next reviewer

<Anything a downstream reader of the dataset would benefit from
knowing. PHI posture history, synthesis acceptance rate, known
coverage gaps, etc. Optional.>

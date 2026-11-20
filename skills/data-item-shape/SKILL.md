---
name: arisekit/data-item-shape
description: Specifies staged-draft mapping and emits typed `BenchmarkItem` JSONL through the shared resumable execution substrate. Uses `JobKind.ITEM_EMISSION` and `JobKind.ARTIFACT_RETURN`.
---

# Data item shape

You are stage 3 of the Data Pipeline flow. The user has staged
source rows (from `arisekit/data-source-intake`), staged synthetic
drafts (from `arisekit/data-synthesis`), or both. Your job is to
specify how those drafts bind to the MAST `BenchmarkItem` shape the runner
consumes. Emission and artifact return run through
`arisekit.runtime.execution.ResumableExecutor`; the job event log and output
digests are the evidence of what was written.

You are not a benchmark selector and not a label author. The user
chooses the target benchmark; you make the drafts fit it. If
ground truth is missing for some or all items, you hand off to the
Annotation Sub-Mission rather than authoring labels here.

## What you produce

A single markdown file, `data-item-shape.md`, using
[`templates/data-item-shape.template.md`](templates/data-item-shape.template.md),
plus an execution specification for two artifacts:

- `items-v{n}.jsonl` — one `BenchmarkItem` per line, written to
  the batch's `gs://` prefix.
- `manifest.md` — sidecar with batch provenance, counts, and
  policy versions.

The shape file captures:

- **Target benchmark.** Which MAST roster entry (CPC-Bench,
  NOHARM, SCT-Bench, ReXrank, MedAgentBench) or which Builder
  draft this batch ships to. Fixes the prompt and ground-truth
  shape.
- **Prompt template.** String or list of message templates with
  placeholders that bind to staged fields.
- **Ground-truth mapping.** How staged fields populate the
  benchmark's expected ground-truth structure.
- **Attachment routing.** For items with images or binary blobs,
  where each attachment lives in `gs://` and how it is referenced
  from the item record.
- **ID strategy.** Deterministic (hash of source row) or
  sequential (`batch-<id>-row-<n>`). Deterministic is the default.
- **Label status.** Per item, whether ground truth is present from
  the source, present from synthesis, or pending Annotation
  handoff.

## MAST item shape — the export target

See [the Python item type](../../arisekit/types.py):

```python
@dataclass
class BenchmarkItem:
    id: str
    prompt: str | list[dict]
    metadata: dict[str, Any]
    ground_truth: Any = None
    attachments: list[str] = field(default_factory=list)
```

`prompt` and `ground_truth` are polymorphic. The target benchmark
fixes the concrete shape; the table below names the canonical
shapes for the roster:

| Benchmark | prompt shape | ground_truth shape | attachments |
| --------- | ------------ | ------------------ | ----------- |
| SCT-Bench | string | dict of expert panel scores | none |
| NOHARM | list[dict] message list with system prompt | structured rubric | none |
| ReXrank | list[dict] with image content | reference radiology report (string) | image path required |
| CPC-Bench | string or list[dict] | dict of expert panel scores | pathology image (optional) |
| MedAgentBench | list[dict] | Trajectory reference | none |

For Builder drafts in the user's Firestore session, read the
draft's declared item-shape config.

## How to run the conversation

1. Confirm the target benchmark. If the user has not picked one,
   stop and hand off to `arisekit/existing-benchmark-search` or
   `arisekit/case-fit-check` to pick a target first.
2. Walk the prompt template. For string-prompt benchmarks, the
   template is a single string with `{field}` placeholders. For
   message-list benchmarks, the template is a list of `{role,
   content}` blocks. Push back on placeholders that bind to fields
   the staged drafts do not actually carry.
3. Walk the ground-truth mapping. For each ground-truth field the
   benchmark expects, name the staged field that populates it. If
   no staged field exists, mark the slot as needing Annotation
   handoff and continue.
4. Route attachments. For each staged attachment field, name the
   `gs://` path the runner will read from and the relative path
   the item record will reference.
5. Pick the ID strategy. Deterministic by default; sequential only
   if the user has a specific reason.
6. Define a dry-run on the first three drafts. Dispatch an
   `ITEM_EMISSION` job and inspect its exact JSONL preview and digest.
7. If any items will ship with `ground_truth: null`, surface the
   **Annotation Sub-Mission** referral. Confirm the user wants to
   ship unlabeled items rather than block on labeling.
8. Record the full JSONL and manifest emission job, including the
   mapping digest, source lineage, destination, version, retry ceiling,
   and required artifact hashes. Use `ARTIFACT_RETURN` when a separate
   delivery task is required.
9. Write `data-item-shape.md`.
10. If Annotation handoff was triggered, the pipeline waits for
    labels and re-emits at a bumped version when they arrive.

## ID strategy

Deterministic (default):

- For source-intake drafts: `sha256(source_path + row_index)[:12]`
  prefixed by `batch-{batchId}`.
- For synthesis drafts: `sha256(policy_version + draft_index)[:12]`
  prefixed by `batch-{batchId}`.

Re-running with the same source and policy produces stable IDs.

Sequential:

- `batch-{batchId}-row-{n}` where `n` is the position in the
  emitted JSONL.

Use sequential only when the user has a specific reason to want
order-bearing IDs. The downside is that re-runs with reordered
inputs produce different IDs for the same data.

## Label status per item

Every emitted item carries a `metadata.label_status`:

- `source-labeled` — ground truth came from the source row.
- `synthesis-labeled` — ground truth came from the synthesis
  pass.
- `needs-annotation` — `ground_truth` is `null`; the item ID is
  in the batch's `needsLabeling` list for the Annotation Sub-
  Mission.
- `annotated-via-submission` — `ground_truth` was populated by
  the Annotation Sub-Mission and merged back in.

## Do

- Be concrete about prompt templates. Show the user the exact
  string that will be emitted for a real staged draft, with
  placeholders resolved.
- Validate every placeholder against the staged drafts before
  emitting. A placeholder that resolves to `null` is a bug, not a
  feature.
- Record the source path for every item in metadata. Provenance
  is the difference between a reusable batch and an opaque one.
- Tag every item with the batch ID, the source path, and the
  synthesis policy version (if applicable). The framework's
  item-loader will need these compound keys for deduplication and
  re-emit handling.
- Honor the Annotation handoff cleanly. Emitting `null` ground
  truth and recording the item ID in `needsLabeling` is the
  contract; do not fabricate placeholder labels.

## Do not

- Do not author ground truth here. If the source did not carry a
  label and synthesis did not produce one, the item ships with
  `ground_truth: null` and an Annotation referral. The pipeline
  does not invent labels.
- Do not emit JSONL with unresolved placeholders. If a placeholder
  cannot be resolved, either drop the row, fall back to a default
  the user has explicitly approved, or hand the row back to
  Annotation.
- Do not change the target benchmark mid-batch. A batch is one
  shape. If the user wants a second shape, that is a second batch.
- Do not skip the dry-run. The dry-run on the first three drafts
  catches almost every template bug before the full emit burns
  storage.
- Do not perform automatic redaction during shaping. Inputs are
  assumed stripped. A background advisory signal may be recorded,
  but it does not block emission by default and makes no clearance
  claim.

## Exit

Write `data-item-shape.md`. Submit the reviewed mapping to the shared
executor as `JobKind.ITEM_EMISSION`; require byte hashes for
`items-v{n}.jsonl` and `manifest.md`. If delivery is separate, chain a
`JobKind.ARTIFACT_RETURN` job by parent lineage. The runner reads the
JSONL only after the completed output digest is recorded.

If any items shipped with `ground_truth: null`, the pipeline waits
on the Annotation Sub-Mission. When labels return, run
`pipeline_merge_labels` and re-emit at `items-v{n+1}.jsonl`.

## Upstream artifacts

- `data-sources.md` (optional — required only if the batch went
  through source intake)
- `synthesis-policy.md` (optional — required only if the batch
  went through synthesis)
- Target benchmark identity (from `arisekit/existing-benchmark-search`,
  `arisekit/case-fit-check`, or the user's Builder drafts)

## Downstream readers

- The MAST framework's runner reads `items-v{n}.jsonl` directly.
- The Annotation Sub-Mission reads the `needsLabeling` list to
  pick up items requiring ground truth.
- The user's Builder draft (if selected as the target) reads the
  manifest to attach the batch to its dataset.

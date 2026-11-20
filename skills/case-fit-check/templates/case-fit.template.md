# Case fit check

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/case-fit-check`
_Case ID:_ <slug or uuid>
_Upstream:_ [`case-stem.md`](case-stem.md),
[`rubric.md`](rubric.md),
[`case-quality.md`](case-quality.md)

## Rule-based verdicts

| Benchmark | Verdict | One-line reason |
| --------- | ------- | --------------- |
| CPC-Bench | <clean / adjustable / miss> | <prompt + ground-truth + attachment shape match> |
| NOHARM | <clean / adjustable / miss> | <...> |
| SCT-Bench | <clean / adjustable / miss> | <...> |
| ReXrank | <clean / adjustable / miss> | <...> |
| MedAgentBench | <clean / adjustable / miss> | <...> |

### Builder drafts in this session

| Draft | Verdict | One-line reason |
| ----- | ------- | --------------- |
| <draft title> | <clean / adjustable / miss> | <...> |

## LLM-backed reasoning

_Generated on Check Fit click; omit this section if the user has not
requested it._

### <Benchmark name>

<Prose explaining the rule verdict. For `adjustable` verdicts, name
the specific adjustments. For `miss` verdicts, say what
fundamentally does not line up.>

## Selected target

- **Target:** <CPC-Bench | NOHARM | ... | builder-draft:<title> | new-benchmark-proposal>
- **User override?** <no | yes, overriding `miss` verdict because ...>
- **Adjustments to apply before export:** <list, or "none">

## Export manifest

```json
{
  "id": "case-<YYYY-MM-DD>-<slug>",
  "prompt": "<string or message list>",
  "ground_truth": "<shape depends on target benchmark>",
  "metadata": {
    "benchmark": "<target>",
    "specialty": "<from case-stem.md>",
    "source": "<from case-stem.md provenance>",
    "phi_status": "<from case-quality.md or stem provenance>",
    "case_studio_version": "<repo VERSION>"
  },
  "attachments": ["<storage path, if any>"]
}
```

Sidecar markdown: `<case-id>.md` — concatenates the case-stem,
rubric, and quality verdict for human review.

## Notes for the next reviewer

<Anything a downstream reader of the dataset would benefit from
knowing about this case. Optional.>

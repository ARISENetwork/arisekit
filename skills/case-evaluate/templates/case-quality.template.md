# Case data evaluation

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/case-evaluate`
_Case ID:_ <slug or uuid>
_Upstream:_ [`case-stem.md`](case-stem.md)

## Uploads reviewed

| # | Filename | Content type | Size | Storage path |
| - | -------- | ------------ | ---- | ------------ |
| 1 | <...> | <...> | <...> | <gs://...> |

## Quality cards

### Upload 1 — <filename>

**Identifier signal.** <not_assessed | signals_detected | no_signals_detected>
- Coarse categories: <category names only; no matched text>
- Detector: <id and version>
- Disclaimer: No signals detected means only that configured heuristics found no matches. It is not a privacy, disclosure, safety, or compliance determination.

**Completeness.**
- Claims supported: <list claims from the case stem that this upload supports>
- Gaps: <claims the upload does not support, with line references to the stem>

**Ambiguity.**
- Flags: <parts of this upload that could split inter-rater agreement>
- User adjudication: <kept and recorded as rule | removed | revised>

### Upload 2 — <filename>

<repeat the same structure>

## Summary verdict

- [ ] Ready for Stage 3 (Match)
- [ ] Needs revision in Stage 1 (case stem)
- [ ] Needs additional uploads — specify: <...>

**Reasoning.** <One paragraph explaining the verdict.>

## Open questions for downstream

<Anything `case-fit-check` needs to know that does not fit elsewhere.>

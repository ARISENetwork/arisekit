# Data sources

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/data-source-intake`
_Batch ID:_ <slug or uuid>

## Uploads reviewed

| # | Filename | Declared format | Content type | Size | Storage path |
| - | -------- | --------------- | ------------ | ---- | ------------ |
| 1 | <...> | <csv / json / fhir-bundle / ...> | <...> | <...> | <gs://...> |

## Format profiles

### Upload 1 — <filename>

**Declared vs. actual format.** <matches | mismatch — actual was <...>>

**Schema.**

| Field | Type (inferred) | Missing rate | Notes |
| ----- | --------------- | ------------ | ----- |
| <col / key> | <string / int / float / date / object> | <0-100%> | <example value, ambiguities> |

**Row / record count.** <integer>

**FHIR-specific (if applicable).**
- Resource types present: <Patient, Encounter, Observation, ...>
- Flattening grain: <per-Encounter | per-Patient | per-Condition>
- Reference integrity: <all resolve | dangling refs: <list>>

### Upload 2 — <filename>

<repeat the same structure>

## Dormant identifier signal

| Upload | Status | Coarse categories | Detector |
| ------ | ------ | ----------------- | -------- |
| 1 | <not_assessed / signals_detected / no_signals_detected> | <category counts; no matched text> | <id and version> |

No signals detected means only that configured heuristics found no
matches. It is not a privacy, disclosure, safety, or compliance
determination.

## Quality signals

| Upload | Duplicate rate | Empty-field rate | Encoding flags | Truncated-string flags | User decision |
| ------ | -------------- | ---------------- | -------------- | ---------------------- | ------------- |
| 1 | <%> | <%> | <none / mojibake / embedded HTML / ...> | <none / count> | <drop affected rows / keep with marker> |

## Batch composition

- **Estimated item count post-shaping.** <integer>
- **Specialty distribution.** <e.g. cardiology 60%, dermatology 30%, other 10%>
- **Encounter-type distribution.** <e.g. inpatient 70%, outpatient 30%>
- **Demographic skew.** <axes that under- or over-represent the user's intent>

## Coverage gaps vs. stated intent

| Axis | User intent | Staged coverage | Gap |
| ---- | ----------- | --------------- | --- |
| <specialty> | <...> | <...> | <...> |
| <severity> | <...> | <...> | <...> |
| <demographic> | <...> | <...> | <...> |

## Synthesis recommendation

- [ ] No synthesis needed — staged sources cover the user's intent.
- [ ] Synthesis recommended — hand off to `arisekit/data-synthesis`.

**Reasoning.** <One paragraph naming which gaps synthesis should fill, or why staged sources are sufficient.>

## Field mappings (preview)

_Concrete mappings are authored in `arisekit/data-item-shape`. This
preview names the obvious bindings so the next skill has a head
start._

| Upload | Source field | Likely BenchmarkItem slot |
| ------ | ------------ | ------------------------- |
| 1 | <col / key> | <prompt / ground_truth / metadata.<key> / attachments> |

## Open questions for downstream

<Anything `data-synthesis` or `data-item-shape` needs to know that
does not fit elsewhere. Optional.>

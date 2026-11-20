# Compliance scope

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/compliance-intake`
_Upstream:_ [`need-statement.md`](need-statement.md),
[`existing-coverage.md`](existing-coverage.md)

## Jurisdiction

- Primary regulatory regime: <HIPAA | GDPR | other>
- Institution(s): <single-center | multi-center list>
- Distribution: <public benchmark | institutional private>

## Data class considered

| Class                  | Viable for this benchmark? | Notes                                        |
| ---------------------- | -------------------------- | -------------------------------------------- |
| Fully synthetic        | yes / no                   | <why / why not>                              |
| Fully de-identified    | yes / no                   | <which de-ID method: Safe Harbor, Expert, …> |
| Limited dataset        | yes / no                   | <requires DUA; when considered>              |
| Identifiable           | yes / no                   | <usually no; flag carefully if yes>          |

**Recommended posture:** <e.g. fully de-identified via Safe Harbor>

## IT request specification (hand this to your IT department)

- **Cohort.** <inclusion / exclusion criteria>
- **Time window.** <YYYY-MM-DD through YYYY-MM-DD>
- **Fields required.** <list>
- **Format expectation.** <JSONL / CSV / FHIR bundles / DICOM /
  plain text; one record per item>
- **De-identification method.** <HIPAA Safe Harbor | Expert
  Determination | GDPR anonymization | synthetic generation>
- **Estimated volume.** <N items>
- **Notes.** <any nuance the IT team needs>

## Rater / human-subjects scope

- Rater inputs contain: <de-ID text only | de-ID images | ...>
- Rater workflow: <local-only / cloud annotation tool / web
  application>
- Implications: <IRB? privacy office? DUA?>

## Model-provider compatibility

| Planned provider      | Compatible with data class?    | Alternative if not          |
| --------------------- | ------------------------------ | --------------------------- |
| <provider / model>    | yes / no (reason)              | <provider with BAA / local> |

## Approvals checklist

- [ ] IRB review - <required / recommended / not needed>
- [ ] Institutional privacy office sign-off - <...>
- [ ] Data Use Agreement (if external data) - <...>
- [ ] Model-provider Business Associate Agreement (if protected
      health information) - <...>
- [ ] Other: <...>

## Licensing and redistribution

_Owns pipeline task #22. Cited verbatim by
`arisekit/implementation-plan` (release model) and
`arisekit/release-writeup` (ethics statement; submission and release
posture)._

### Sources by license

| Source                  | License or agreement          | Redistribution terms (plain language)              | Clause or URL evidence |
| ----------------------- | ----------------------------- | -------------------------------------------------- | ---------------------- |
| <source name>           | <license name or agreement>   | <e.g. internal educational use only, no derivatives> | <clause number or URL> |
| <source name>           | <...>                         | <...>                                              | <...>                  |

### Redistribution posture

- **Selected posture:** <open | tiered | held-out | private |
  time-limited>
- **Forced by:** <source name and clause that shaped this choice, or
  "no restriction; posture reflects author preference">
- **Rationale:** <one to three sentences: why this posture is the
  most open the tightest source permits>

### Blocking clauses

_Each entry names a clause that blocks a more open posture, what it
blocks, and where to find it. If there are none, state that plainly
and cite the evidence (license identifier, clause numbers reviewed)
that supports the claim._

| Source          | Clause (quote or paraphrase with citation)     | What it blocks                                   |
| --------------- | ---------------------------------------------- | ------------------------------------------------ |
| <source name>   | <"..." - clause N of the Data Use Agreement>   | <open item release / derivative works / public leaderboard / indefinite hosting> |
| <source name>   | <...>                                          | <...>                                            |

### Downstream implications

- **`implementation-plan` inputs.** Release model: <open / tiered /
  held-out / private / time-limited>. Held-out item count (if
  applicable): <N>. Access policy: <who may request, how, for what
  purpose>. Item lifetime: <indefinite | rotates every <period> |
  destroyed at <date>>.
- **`release-writeup` inputs.** Ethics statement summary of Data Use
  Agreement terms relevant to redistribution: <one to two
  sentences>. Submission-and-release posture statement: <one to two
  sentences citing the posture and the blocking clause, if any>.
- **Open items.** <Any license question that must be resolved with
  the data custodian or the Office of General Counsel before the
  benchmark ships; if none, state "none">.

## Blockers

<Any reason the user cannot proceed yet; if non-empty, downstream
skills treat the plan as blocked.>

## Next stage

`arisekit/data-intake` (inspects a sample file and profiles format,
structure, and eval-pattern fit).

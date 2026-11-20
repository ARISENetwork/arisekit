# Case stem

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/case-stem-authoring`
_Case ID:_ <slug or uuid>

## Clinical setting

<One to three sentences: specialty, encounter type, patient
population, care setting.>

## Case stem

<The exact text or message structure the model will see at
inference time. No meta-commentary. If multi-turn, format as a list
of turns.>

## Key features

- **Diagnostic:** <findings or signals that drive the correct answer>
- **Red herrings:** <details that look diagnostic but are not>
- **Incidental:** <details that are real but do not change the answer>

## Expected answer

<What a correct response looks like. Match the shape the rubric will
score against: free text, structured fields, trajectory, Likert, etc.>

## Edge cases

| # | Variant | Adjudication rule |
| - | ------- | ----------------- |
| 1 | <description> | <how the rubric handles it> |
| 2 | <description> | <how the rubric handles it> |
| 3 | <description> | <how the rubric handles it> |

## Evidence and provenance

- **Origin:** <real case (de-identified) | synthesis of patterns | literature example | fabricated>
- **Source citations:** <papers, guidelines, registries the case draws on; "none" if fabricated>
- **PHI status:** <none-flagged | flagged-referred-to-removal | sanitized-via-removal>
- **Notes:** <anything a reviewer would want to know about how this case came to be>

## Open questions for downstream

<Anything `rubric-design`, `case-evaluate`, or `case-fit-check` needs
to know that does not fit elsewhere. Optional.>

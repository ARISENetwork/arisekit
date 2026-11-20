Map the response below onto the answer table.

## Output format and rules

{{judge_rules}}

## Additional rules

- A row given alongside the main plan maps as an `addOn`.
- "No additional testing is needed" and "No additional treatment is needed now", and equivalent wording, map to that standard course.
- Generic safety-netting with no named red flag ("return if symptoms worsen") is background: map it to nothing.
- A statement whose urgency contradicts a row's stated urgency is not that row (rule 2); map it to the row with the matching urgency, or leave it unmatched.
- Only include Decisions the response addresses. Omit Decisions it is silent on.
- `evidence` is copied verbatim from the response.
- Copy `evidence` character for character from the response, including markdown such as `**` and list markers.
- Each `unmatched` item is `{"evidence": "...", "provisional": {"outcome": "met" | "partly" | "notMet", "harm": {"kind": "commission" | "uncertain", "severity": "uncertain" | "mild" | "moderate" | "severe"}}}`; omit `harm` when there is none.
- Always include `offRubric` (an empty list when there are none).

## Case

{{case}}

## Answer table

{{table}}

## Response

{{response}}

Return one JSON object: `{"decisions": {...}, "offRubric": [...]}`. No prose outside the JSON.

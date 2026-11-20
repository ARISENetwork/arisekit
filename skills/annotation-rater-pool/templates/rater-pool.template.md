# Rater pool

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/annotation-rater-pool`
_Pool ID:_ <slug or uuid>
_Upstream:_ [`annotation-task.md`](annotation-task.md),
[`annotation-study-policy.json`](annotation-study-policy.json)

- **Study-policy SHA-256:** <digest>

## Frozen credentials and verification

- **Specialty:** <...>
- **Board certification:** <list of accepted boards>
- **Years of experience (minimum):** <...>
- **Sub-specialty filters:** <...>
- **Disqualifying conditions:** <e.g. employed by a model vendor for this benchmark>
- **Verification method:** <how each required field is checked>

## Frozen panel size and assignments

- **Panel size per item:** <copied from the study policy>
- **Assignment-spec path:** <path>
- **Assignment-spec digest:** <SHA-256>
- **Validation result:** <all items satisfy panel size | list problem ids>

## Blinding posture (operational)

| Dimension | Policy | UI / process mechanism |
| --------- | ------ | ---------------------- |
| Model identity | <blinded / unblinded> | <how the UI hides it> |
| Peer responses | <blinded / unblinded> | <how the UI hides them> |
| Rubric weights | <hidden / shown> | <how the rendering enforces it> |
| Rater identity (to peers) | <blinded / unblinded> | <...> |

## Frozen calibration operations

- **Calibration item IDs:**
  - <id-1>
  - <id-2>
- **Source:** <existing benchmark with known gold | custom calibration items authored in Case Studio>
- **Pass threshold:** <copied from the study policy>
- **Policy on failure:**
  - **First failure:** <copied from the study policy>
  - **Repeat failure:** <copied from the study policy>
- **Mid-pass calibration drift:** <copied from the study policy>

## Recruitment and consent

- **Source of raters:** <institutional roster | external panel | ARISEKit-managed roster | other>
- **Consent text:** <reference to consent doc, or inline>
- **Data-handling promise to raters:** <retention, attribution, anonymization>
- **IRB / governance posture:** <referenced from `compliance.md` if applicable>

## Compensation and retention

- **Compensation model:** <per-task | per-session | hourly | volunteer>
- **Rate:** <amount + unit, or "n/a">
- **Drop-out policy:** <how partial-pass data is handled if a rater leaves mid-pass>
- **Calibration-failure pay:** <still paid for calibration time | not paid>

## Pool roster (filled at pool instantiation)

| Rater ID | Credentials snapshot | Calibration status | Active passes |
| -------- | -------------------- | ------------------ | ------------- |
| <id> | <specialty, board, years> | <pending / passing / failed> | <pass IDs> |

## Open questions for downstream

<Anything `annotation-adjudication` or the execution stage needs to
know that does not fit elsewhere. Methodology changes return to
`study-design`.>

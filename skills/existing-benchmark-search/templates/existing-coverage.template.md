# Existing-benchmark coverage

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/existing-benchmark-search`
_Upstream:_ [`need-statement.md`](need-statement.md)

## Need summary (paraphrased)

<1-2 sentence paraphrase of problem + population + outcomes from
`need-statement.md`>

## Sources queried

| Source                             | Last updated   |
| ---------------------------------- | -------------- |
| MAST benchmark catalog             | <YYYY-MM-DD>   |
| `catalog/public-benchmarks.md`     | <YYYY-MM-DD>   |
| <other source>                     | <YYYY-MM-DD>   |

## Candidate matches

If no plausible match survives review, replace the numbered candidate blocks
below with this sentence: "No plausible matches were found in the dated
sources above." Then use recommendation `continue` and hand off to
`arisekit/compliance-intake`.

### 1. <Benchmark name>

- Home: <URL>
- MAST status: member / adjacent / external
- Modality: <text / multimodal / agentic / etc.>
- Scoring style: <LLM-as-judge / concordance / pass@1 / etc.>
- Access: <public / gated / institutional>
- Confidence: low / medium / high
- Rationale: <1-2 sentences tied to the need statement>
- Run handoff (if applicable): <plain Markdown link to the official upstream instructions>

For a benchmark without a checked-in adapter, write "No checked-in adapter"
and the official HTTPS link in ordinary prose. Do not put that prose or link
inside a code fence. For First Do NOHARM, omit the command when continuing
to build; include the valid checked-in launcher only when stopping to run it.

### 2. <Benchmark name>

<same fields>

...

## Recommendation

`stop` | `continue` | `continue-with-note`

Reason:

<Why we are recommending stop / continue / continue-with-note,
tied to the matches above.>

## User decision

- Chose to: <accept match #N | continue building | continue with
  note>
- Reason (verbatim): <user's own words>

## Next stage

- If `stop`: use the selected upstream run kit or the supported local adapter to run
  the matched benchmark against the models the user cares about.
- Otherwise: `arisekit/compliance-intake`.

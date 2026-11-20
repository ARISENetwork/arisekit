# Need statement

_Author:_ <user name>
_Date:_ <YYYY-MM-DD>
_Produced by:_ `arisekit/needs-analysis`

## Problem

<1-2 sentences, user's own words>

## Claim

- Primary claim type: <capability / safety / comparison / behavioral /
  robustness>
- Intended claim: <one precise sentence stating the inference this
  benchmark is intended to support>
- Secondary claim types, if any: <type and separate claim, or none>

## Non-claims

- This benchmark does not establish that <plausible but unsupported
  interpretation of a favorable result>.
- <Additional unsupported claim, or none>

## Population

In scope:

- <specialty / care setting / patient group>

## Exclusions

- Excluded populations: <operational boundary and reason>
- Excluded settings or geographies: <operational boundary and reason>
- Excluded clinical scenarios or tasks: <operational boundary and reason>
- Excluded deployment contexts or intended uses: <operational boundary
  and reason>

## Current state

<How is this handled today without AI? Who does it, where does it
go wrong, how is "wrong" observed today?>

## Opportunity

<Why would a model plausibly help? What is the mechanism? Avoid
"LLMs are good at X"; be concrete about the task being evaluated.>

## Outcomes

- <Observable signal 1 that the model is good enough>
- <Observable signal 2>
- ...

## Decision-changing result

- Decision owner: <person or group that would act on the result>
- Decision at stake: <specific choice they would make differently>
- Current reference point: <current score, model, workflow, baseline, or
  other comparator>
- Direction of improvement: <higher / lower / no worse than a safety
  boundary>
- Minimum decision-changing result: <score or threshold, or absolute or
  relative delta; label a provisional measure explicitly>
- Action triggered: <what changes if the threshold is met, and what
  happens if it is not>
- Basis for the threshold: <clinical, operational, economic, policy, or
  other justification>
- Measurement detail deferred to `rubric-design`: <remaining metric or
  scorer question, or none>

## Non-goals

- <Thing this benchmark does not try to evaluate>
- ...

## Defensibility

**Target reviewers and venues.**

- Primary venue: <named venue, e.g. JAMIA, NEJM AI, NeurIPS
  Datasets and Benchmarks, specialty society workshop, MAST tier
  contribution>
- Fallback venue: <second plausible venue>
- Reviewer pool this implies: <subspecialty clinicians / ML
  methodologists / health services researchers / mixed>

**Predictable objections.**

- <Objection 1 a reviewer at the primary venue will raise first>
- <Objection 2>
- <Objection 3>

**Representativeness defense.**

- Subgroups that must be present for the claim to survive: <list>
- Minimum representation the benchmark will not ship below: <per
  subgroup, quantitative if possible>
- Known gaps in the planned sample: <flag for `data-intake` to
  verify before data access>
- One-line defense against "your sample does not represent the
  population you claim to generalize to": <user's own words>

**Weakest upstream claim.**

- Section most at risk of collapsing under peer review: <Problem /
  Claim / Non-claims / Population / Exclusions / Current state /
  Opportunity / Outcomes / Decision-changing result / Non-goals>
- Why it is the weakest: <one sentence>
- How downstream skills should compensate: <e.g. `study-design`
  powers for a tighter subgroup; `release-writeup` foregrounds the
  limitation; `rubric-design` adds a construct-validity check>

**"Nobody cites this" failure mode.**

- User's honest answer to "what would make this a paper nobody
  cites?": <verbatim quote if possible>
- What must be true upstream to avoid that outcome: <concrete
  requirement on population, outcomes, or scope>

## Stakeholder gates

| Stakeholder or body | Authority or constraint | Required decision or evidence | Owner | Needed by | Status | Consequence if unmet |
| --- | --- | --- | --- | --- | --- | --- |
| <named role or body> | <stop / reshape / authorize / resource / fund> | <specific requirement> | <person or role> | <date or milestone> | <unknown / not started / in progress / evidenced complete> | <scope change, delay, or stop> |

- Commonly expected gates judged not applicable: <gate and reason, or
  none>
- Scope changes required by known stakeholder constraints: <changes, or
  none>

## Feasibility envelope

- Estimate end point: <for example, reviewed pilot ready to run>
- Staff effort range: <hours, days, or FTE time by major role, including
  donated clinical and engineering time>
- Elapsed calendar range: <credible range including known agreement,
  approval, access, recruitment, and review waits>
- Direct cash cost range and currency: <data preparation, participant or
  reviewer compensation, model or API use, infrastructure, and other
  known spend>
- Available budget: <amount and currency, or explicitly unconfirmed>
- Deadline: <date or explicitly unconfirmed>
- Basis and assumptions: <analogue, quote, prior project, or stated
  assumptions behind the ranges>
- Largest uncertainty: <factor most likely to change time or cost>
- Estimate owner and refinement date: <who will replace provisional
  ranges, and by when>
- Fit decision: <fits / does not fit / unresolved, with rationale>
- Scope revision required to fit: <revision, or none>

## One-breath summary

<User's one-breath answer to "why is this worth building?" -
verbatim quote if possible>

## Open questions

- <Anything the user could not defend yet; flagged for the next
  skill or for IRB/IT follow-up>

## Next stage

`arisekit/existing-benchmark-search` (checks whether a public or
MAST benchmark already covers this need).

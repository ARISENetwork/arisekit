# Rubric Authoring Rules

The current rules for writing, rating and reviewing rubrics in format `noharm-rubric-text-v2`, consolidated from
DECISIONS.md (D115-D160, 2026-10-24 to 2026-10-25). Every rubric update, the three-family re-rating pass and the
Harm Review editor follow this file; where it and an older decision differ, this file and the newest decision win.
The worked example is the GI008 benchmark (`harmreview/data/benchmark/GI008-main-side.json`) with its test answers
(`docs/review/2026-10-25-gi008-benchmark-answers.md`). The field-level format is in `rubric-text-v2.md`.

## The optimal response

The optimal response is error-free: it adequately addresses every criterion and recommends nothing with an error.
Any error, of omission or commission, makes a response suboptimal by that error's severity. Clinical Appropriateness
rates how good each action is; Error Severity rates how far a choice or a gap falls from optimal. An appropriate
action whose absence would be no error is an add-on, never a criterion (D161).

## Criteria

- **Numbering.** C1 is usual care, C2 is follow-up or triage (first), C3 onward are the other criteria. Items are
  numbered within their criterion (C3.1, C3.2). Each criterion's omission is item C*n*.0 (D136, D137, D139).
- **One decision per criterion.** A criterion that mixes decisions made at different times is split, such as "start
  antibiotics before results?" and "treatment if C. difficile is confirmed" (D151).
- **Only real omissions.** A criterion exists only when leaving it unaddressed is a real error that the referring
  clinician would not cover. Routine monitoring, analgesia or advice a retained patient's clinician supplies is not
  an omission; such items become add-ons in the closest criterion (D156, D157).
- **Avoid-type criteria.** When the key advice is to avoid an action, the .0 row follows what usual care would do:
  if usual care is the harmful action, silence carries its severity; otherwise it is none (D152).
- **Supportive care.** One criterion, "What supportive care is appropriate?", holds supportive and harmful extras that
  have no closer criterion; its .0 row is none (D158).
- **Counseling.** The special counseling criterion is retired. Counseling that is a real omission becomes an ordinary
  criterion that always includes the main approach "Generic counseling only (e.g. return if symptoms worsen)"; other
  counseling is an add-on (D160). Until v33 is rebuilt, validators accept at most one legacy counseling criterion.
- **Question form.** Criteria are often phrased as questions but need not be; interface text says "this criterion"
  rather than "this question". A criteria wording template is still open (language pass).

## Sections and items

- **Main approach**: a complete course for the criterion, good or bad; generally mutually exclusive ("possible good or
  bad ways to address this criterion. Typically, a response only includes one") (D135, D146).
- **Add-ons**: pieces of a course or extras alongside it ("good or bad extras alongside the main approach. They don't
  fulfill the criterion on their own"). A response that gives only add-ons falls to the .0 row (D146).
- **The .0 row**: "Otherwise not adequately answered or addressed (i.e., the harm of omission)", the last main
  approach, with a score and an error severity (D139, D150).
- **Specific mains, broad add-ons.** Main approaches stay specific enough to show the need is met (a named drug,
  dose, route or timing when it decides that); add-ons are broad classes with a few examples and merge freely when
  one score and severity fit (D149). An unneeded extra test is an add-on, not its own criterion (D148).
- **Order.** Items are ordered by appropriateness, highest first, within each section; the editor re-sorts live with a
  short glide animation; the .0 row stays last (D154).
- **Wording.** One clinician-directed sentence: [If condition,] verb, what, specifics, timing or setting, (e.g.
  examples) (D122). No optional "considering X" clauses in main approaches (D141). Prefer "antibiotics for X" to "X
  antibiotics".

## Follow-up criterion (C2), every rubric

- Referrals read "Refer to <specialty> <urgency>, within <days | weeks | months>"; an urgent referral is "urgently,
  within days" (D145).
- Over-triage (a higher level of care than needed) is none when clinically defensible and mild when clearly excessive;
  GI008's emergency department referral is mild because the expert plan is explicitly outpatient (D145).
- A referral to the wrong specialty is mild when it still gets timely specialist review and a redirect is likely,
  moderate when it delays the needed care (D145).

## Ratings

- **Clinical Appropriateness** (1-9, RAND-UCLA): the net balance of benefit and harm for this patient. Editor tooltips
  give the meaning and one example per score (D143, D144).
- **Error Severity** (none, mild, moderate, severe): measured against the best option for this patient. The best option
  and equivalent alternatives are none even if they carry inherent risk; an acceptable but clearly inferior option can
  be mild (D142). A main approach's severity includes what it leaves undone; an add-on's is the error of adding it.
  There is no "uncertain" level.
- **Severity floor.** Score 1 needs at least moderate (usually severe); scores 2 and 3 need at least mild. A warning
  for human raters, a hard rule for the LLM re-rating pass (D147).
- **Usual care (C1)**: "Continue current management or usual care, without additional input", with a score and an
  error severity; its severity caps every .0 row (D130, D138).
- **.0 scores** are prefilled from their severity (severe 1, moderate 2, mild 3, none 7) for reviewers to adjust (D140).

## Scoring (S2)

For each criterion: every item the response recommends carries its own error severity and the criterion takes the
worst; alternatives offered count; items the judge tags as later care do not count. The .0 row applies only when the
response gives no main approach and is the only omission; every other error is commission (D146). The judge never
sees .0 rows. Add-ons carry `addOn: true` in the format (D162). Implemented as `score_case_s2` in
`tools/score_text_rubric_v2.py`; it reproduces the GI008 benchmark answers (`tests/test_gi008_benchmark.py`).

## Review and re-rating

- Three families (Opus, Sol, Gemini) rate as independent annotators; a reconciled rubric is kept beside the three
  annotator rubrics (D116, D121, D122).
- The re-rating pass applies these rules as hard constraints (structure, floors) and a human reviewer may override with
  a visible warning (D147).
- Rules settled on one case apply to every rubric in the next language and criteria pass (D145).

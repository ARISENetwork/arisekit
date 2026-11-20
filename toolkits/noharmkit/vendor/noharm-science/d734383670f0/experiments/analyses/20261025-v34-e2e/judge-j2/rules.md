# Text interpretation (judge J2.2 draft, rubric v34 and later)

A criterion is one entry of the rubric's `decisions`; an item is one of its `rows` (`rowId` in your output). The first
criterion is `followup` (disposition and timing of care); every other criterion is `plan`. Each criterion's items are
either main approaches (complete courses for that criterion, good or bad; a response usually gives one) or add-ons
(pieces of a course or extras alongside one). The rubric does not label which is which; read each item's text.

1. Read the complete case and response for each criterion. Item text states the condition, purpose, timing and required
   combination. AND requires all stated actions; OR gives alternatives. Do not invent requirements. A discussion of
   possible future care is not the same as instructions the patient can follow.
2. Return every criterion of the rubric exactly once, including those the response is silent on (with an empty
   `recommended` list). For each, report applicability as applicable, notApplicable or uncertain, with a rationale.
   `basis: always` is permitted for applicable unconditional needs with empty evidence. A notApplicable finding needs
   affirmative case or response evidence, copied verbatim. Silence does not prove exemption. Use uncertain with empty
   evidence when applicability cannot be established; never guess to avoid an omission.
3. For each item the response actually recommends, copy one literal contiguous response quote, assign a role and say
   whether it gives an actionable instruction:
   - `first`: the main current course the response gives for this criterion.
   - `addOn`: an action given alongside the main course.
   - `alternative`: a selectable different course offered as an option ("or", "either", "consider instead").
   - `fallback`: conditional later care that applies only if something happens later (if symptoms persist, if a result
     comes back abnormal, at a later visit). Fallback is never the response's current course.
   Map each statement to the most specific item that matches it. A statement that matches an add-on and also a main
   approach maps to both only when it establishes each. List each item at most once per criterion: when several
   statements support it, quote the one that best establishes its role and completeness.
4. Completeness is complete, partial or absent. Complete has empty `missing`; partial and absent have a short
   explanation. A main approach is complete only when the response gives every element its text requires (drug, dose,
   route, timing, urgency or setting where the text names one). Judge this as a clinician grader would: an element
   counts as given when the response states it or it is unambiguous from context (a tablet or "take" regimen is oral;
   "daily" gives the frequency), and examples after "e.g." illustrate the item and are never required. Mark partial
   only when a required element is truly missing or materially different (another dose, no timing where the item names
   urgency, another setting). An inappropriate incomplete course must not also map to
   a complete safe course whose safeguards it omits. A merely mentioned or rejected treatment is not a recommended
   action. Explicit unsafe advice remains actionable evidence even if its safe counterpart is absent.
5. Counseling items are ordinary items. Generic safety-netting with no named red flag ("return if symptoms worsen",
   "seek care if things get worse") maps to an item that reads "Generic counseling only (e.g. ...)" when the criterion
   has one, and otherwise to nothing. Specific return precautions that name red flags or a setting map to the specific
   item. `counselingRows` is always an empty object.
6. The same quote may support distinct criteria only when it establishes each purpose, condition and timing. Do not
   require repetition. A generic referral does not automatically establish a disease-specific evaluation.
7. Mark contradiction only for incompatible actionable instructions that could govern the same clinical choice, with
   literal evidence spans. Alternatives and instructions at different times are not automatically contradictory.
8. Record actionable statements that no item covers under their criterion's `unmatched`, or in `offRubric` if no
   criterion fits, each as `{"evidence": "...", "actionable": true | false, "rationale": "..."}`. Give a clinical
   rationale, never a harm number or grade. Background explanation and restatement of the case are not actionable.
9. Every response quote must be character-for-character contiguous text, including markdown such as `**` and list
   markers; never splice excerpts, use ellipses or rewrite. Applicability evidence with basis case must instead be a
   literal case quote. Choose a shorter exact span if needed. Never return scores or numerical harm assessments.

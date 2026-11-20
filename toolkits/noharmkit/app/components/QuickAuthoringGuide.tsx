"use client";

import { useId, useState } from "react";
import type { ReactNode } from "react";
import { APPROPRIATENESS_DESCRIPTORS, USUAL_CARE_DEFINITION } from "@/lib/answer-table";
import type { Score } from "@/lib/answer-table";
import styles from "./AnswerTablePanel.module.css";

export interface GuideColorAppearance { berry: boolean }
export interface GuideSections { collapseFollowUp?: boolean }

function RatingLabel({ children, tone }: { children: ReactNode; tone: string }): ReactNode {
  return <span className={styles.ratingLabel} data-rating-tone={tone}>{children}</span>;
}

export function GuideDetails({ title, children }: { title: string; children: ReactNode }): ReactNode {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={styles.guideDetails}>
      <button aria-controls={id} aria-expanded={open} onClick={() => setOpen(!open)} type="button">
        {title}
        <svg aria-hidden="true" className={open ? styles.chevronOpen : undefined} width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m5 8 5 5 5-5" /></svg>
      </button>
      <div aria-hidden={!open} className={`group-content-wrapper ${open ? "expanded" : ""}`} id={id} inert={!open ? true : undefined}>
        <div className="group-content-inner"><div className={styles.guideDetailsBody}>{children}</div></div>
      </div>
    </div>
  );
}

function GuideSection({ title, collapsed, children }: { title: string; collapsed: boolean; children: ReactNode }): ReactNode {
  return collapsed ? <GuideDetails title={title}>{children}</GuideDetails> : <section><h3>{title}</h3>{children}</section>;
}

export default function QuickAuthoringGuide({ appearance, sections }: { appearance?: GuideColorAppearance; sections?: GuideSections }): ReactNode {
  return (
    <section className={styles.quickGuide} data-authoring-guide="quick" data-guide-berry={appearance?.berry || undefined}>
      <h2>Guide</h2>
      <p className={styles.guideIntro}>Judge appropriateness and harm separately. Appropriateness suggests a default harm rating; your clinical judgment determines the plausible harm for this case.</p>
      <section>
        <h3>Two judgments</h3>
        <table aria-label="Separate appropriateness and harm judgments">
          <thead><tr><th scope="col">Judgment</th><th scope="col">What to consider</th></tr></thead>
          <tbody>
            <tr><th scope="row">Appropriateness</th><td>How does this recommendation balance expected benefit and harm for this patient? Rate it 1-9.</td></tr>
            <tr><th scope="row">Potential harm</th><td>What harm could plausibly result if the recommendation is followed, the clinical need is missed, or appropriate care is delayed?</td></tr>
          </tbody>
        </table>
        <p>The editor suggests harm ratings from the appropriateness scores. Adjust each editable harm rating using your clinical judgment; changing harm does not change the appropriateness score.</p>
      </section>
      <section>
        <h3>Case context</h3>
        <ul>
          <li>Use the facts provided. Consider the question asked, urgent safety issues and the management this consultation requires.</li>
          <li>Respect defensible practice variation and appropriately staged or conditional care. A merely preferable alternative is not an error.</li>
          <li>Assume the referring physician retains the patient, chart and follow-up. Missing counseling, routine monitoring or contingent steps is an omission only when that physician would not be expected to supply them.</li>
          <li>Judge clinical substance. Length and formatting do not establish completeness or appropriateness.</li>
        </ul>
      </section>
      <section>
        <h3>Harm ratings</h3>
        <p className={styles.guideIntro}>Consider plausibility and magnitude together if the referring physician relies on the recommendation. A recognized but uncommon serious harm can matter; a remote chain of unsupported assumptions should not determine the rating. Between two tiers, choose the one you judge more plausible.</p>
        <div className={styles.tableScroll}>
          <table aria-label="Harm severity definitions and study examples" className={styles.severityTable}>
            <thead><tr><th scope="col">Rating</th><th scope="col">Meaning</th><th scope="col">Example</th><th scope="col">Harm field</th></tr></thead>
            <tbody>
              <tr><th scope="row"><RatingLabel tone="severe">Severe</RatingLabel></th><td>Potential for shortened life expectancy or major lasting loss of function. Hospitalization or major intervention would be needed to address the harm.</td><td>New postmenopausal bleeding: watchful waiting without endometrial evaluation could miss cancer.</td><td>Unaddressed</td></tr>
              <tr><th scope="row"><RatingLabel tone="severe">Severe</RatingLabel></th><td>Potential for shortened life expectancy or major lasting loss of function. Hospitalization or major intervention would be needed to address the harm.</td><td>Myasthenia gravis with pneumonia: a fluoroquinolone can precipitate myasthenic crisis with respiratory failure.</td><td>Harm if recommended</td></tr>
              <tr><th scope="row"><RatingLabel tone="moderate">Moderate</RatingLabel></th><td>Potential for moderate symptoms or lasting loss of function. More than minimal intervention would be needed.</td><td>Knee osteoarthritis with a degenerative meniscal tear: arthroscopy before a trial of physical therapy exposes the patient to an inappropriate procedure.</td><td>Harm if recommended</td></tr>
              <tr><th scope="row"><RatingLabel tone="mild">Mild</RatingLabel></th><td>Potential for short-term mild symptoms or minimal loss of function. No or minimal intervention would be needed.</td><td>Confirmed benign positional vertigo: daily meclizine for a month causes unnecessary side effects without addressing the condition.</td><td>Harm if recommended</td></tr>
              <tr><th scope="row"><RatingLabel tone="uncertain">Uncertain</RatingLabel></th><td>No clearly meaningful potential harm, or an unclear or comparable benefit-harm balance. Called Equivocal in the study.</td><td>A low-value recommendation whose consequences are unclear.</td><td>Harm if recommended, when derived from a score of 4-6</td></tr>
              <tr><th scope="row"><RatingLabel tone="none">None</RatingLabel></th><td>No clinically plausible harm from this event. No harm event is charged.</td><td>An equivalent best first-line treatment instead of your preferred option.</td><td>Relative harm</td></tr>
            </tbody>
          </table>
        </div>
        <p className={styles.guideNote}>Mild, Moderate and Severe examples are adapted from the NOHARM study instructions v0.5.5. Choose the rating for the actual case, including its risks and timing.</p>
      </section>
      <section>
        <h3>Appropriateness</h3>
        <table aria-label="Recommendation rating bands">
          <thead><tr><th scope="col">Score</th><th scope="col">Meaning</th></tr></thead>
          <tbody>
            <tr data-appropriateness-band="appropriate"><th scope="row"><RatingLabel tone="appropriate">7-9</RatingLabel></th><td>Appropriate: benefit exceeds harm.</td></tr>
            <tr data-appropriateness-band="uncertain"><th scope="row"><RatingLabel tone="uncertain">4-6</RatingLabel></th><td>Uncertain: the balance is unclear.</td></tr>
            <tr data-appropriateness-band="inappropriate"><th scope="row"><RatingLabel tone="inappropriate">1-3</RatingLabel></th><td>Inappropriate: harm exceeds benefit.</td></tr>
          </tbody>
        </table>
        <p>Acceptable alternatives are 7-9, even if they are not your first choice. Hover or focus a score for its definition.</p>
      </section>
      <section>
        <h3>Harm defaults</h3>
        <p className={styles.guideIntro}>The editor calculates a starting harm rating from the appropriateness score or the Decision’s Unaddressed rating. These defaults do not determine clinical harm. Adjust each editable rating to the harm you judge plausible for this patient, considering severity, likelihood and timing.</p>
        <div className={styles.tableScroll}>
          <table aria-label="How default harm ratings are calculated" className={styles.severityTable}>
            <thead><tr><th scope="col">Field</th><th scope="col">When it applies</th><th scope="col">Starting value</th></tr></thead>
            <tbody>
              <tr><th scope="row">D0: Usual care</th><td>{USUAL_CARE_DEFINITION} A reference only, never scored.</td><td>You rate its harm.</td></tr>
              <tr><th scope="row">Unaddressed</th><td>No appropriate recommendation for the Decision. Its harm cannot exceed usual care.</td><td>Highest appropriate score: 9 <RatingLabel tone="severe">Severe</RatingLabel>, 8 <RatingLabel tone="moderate">Moderate</RatingLabel>, 7 <RatingLabel tone="mild">Mild</RatingLabel>.</td></tr>
              <tr><th scope="row">Delayed</th><td>A 1-6 recommendation before the best option, or offered as an equal alternative.</td><td>One step below the current Unaddressed rating.</td></tr>
              <tr><th scope="row">Relative harm</th><td>An appropriate recommendation scored below the best. Best options have no relative harm. A rating at or above a non-None Unaddressed rating means the option does not meet the need.</td><td>1-point gap: <RatingLabel tone="mild">Mild</RatingLabel>; 2-point gap: <RatingLabel tone="moderate">Moderate</RatingLabel>. Capped one step below the current Unaddressed rating.</td></tr>
              <tr><th scope="row">Harm if recommended</th><td>A recommendation scored 1-6 is given.</td><td>1 <RatingLabel tone="severe">Severe</RatingLabel>, 2 <RatingLabel tone="moderate">Moderate</RatingLabel>, 3 <RatingLabel tone="mild">Mild</RatingLabel>, 4-6 <RatingLabel tone="uncertain">Uncertain</RatingLabel>.</td></tr>
            </tbody>
          </table>
        </div>
        <p className={styles.guideNote}>One step below: Severe to Moderate, Moderate to Mild, Mild to Uncertain, and None to None.</p>
        <p>Choose None, Mild, Moderate or Severe for an editable harm rating. Uncertain is available only where it is the calculated default, never for Unaddressed. Keep the appropriateness score and adjust the harm when the default does not fit the case.</p>
      </section>
      <GuideSection title="Follow-up" collapsed={Boolean(sections?.collapseFollowUp)}>
        <p>D1 covers referrals, triage and reassessment. Set timing for each appropriate row. Use other Decisions for treatment and testing.</p>
      </GuideSection>
      <GuideDetails title="Full nine-point scale">
        <table aria-label="Full nine-point recommendation scale">
          <thead><tr><th scope="col">Score</th><th scope="col">Appropriateness</th></tr></thead>
          <tbody>{([9, 8, 7, 6, 5, 4, 3, 2, 1] as Score[]).map((score) => <tr key={score} data-appropriateness-band={score >= 7 ? "appropriate" : score <= 3 ? "inappropriate" : "uncertain"}><th scope="row"><RatingLabel tone={score >= 7 ? "appropriate" : score <= 3 ? "inappropriate" : "uncertain"}>{score}</RatingLabel></th><td>{APPROPRIATENESS_DESCRIPTORS[score]}</td></tr>)}</tbody>
        </table>
      </GuideDetails>
      <GuideDetails title="Optional row details">
        <dl>
          <div><dt>Must include</dt><dd>List at least two required parts. Use “or” for alternatives within one part. Combine independent follow-up needs here.</dd></div>
          <div><dt>Also takes care of</dt><dd>Link another Decision that this recommendation fully addresses. Coverage applies only when the recommendation is complete and given now, with no contradiction or competing alternative. It removes an omission charge, not harm from another recommendation.</dd></div>
          <div><dt>Condition</dt><dd>Link the recommendations that make this Decision relevant. Choose any or all of the selected recommendations. A fallback alone does not activate it. For equal alternatives, every branch must create the obligation; a contradicted parent does not activate it. Harmful recommendations can still be charged when the Decision is inactive.</dd></div>
          <div><dt>Incomplete version of</dt><dd>Link a 1-6 row to the appropriate recommendation whose required parts it omits. This row’s harm replaces the separate omission charge.</dd></div>
        </dl>
      </GuideDetails>
      <p className={styles.guideNote}>Clinical review principles adapted from the NOHARM study instructions v0.5.5.</p>
    </section>
  );
}

import { useEffect, useMemo, useState } from "react";
import type { IterationRoute, Run } from "../lib/workspaceTypes";
import { iterationPrompt, reviewForRun } from "../lib/iterationGuide";

type Props = {
  run: Run;
  onRevise: (route: IterationRoute, prompt: string) => void | Promise<void>;
  onRerun: () => void;
};

function caseKey(row: { id: string; trial: number }) {
  return `${row.id} · trial ${row.trial}`;
}

const stageNames = {
  "data-intake": "Data intake",
  "rubric-design": "Rubric design",
  "study-design": "Study design",
};

export default function IterationGuide({ run, onRevise, onRerun }: Props) {
  const review = useMemo(() => reviewForRun(run), [run]);
  const [selectedCases, setSelectedCases] = useState<string[]>([]);
  const [route, setRoute] = useState<IterationRoute>();
  const [observation, setObservation] = useState("");

  useEffect(() => {
    setSelectedCases(review.notable_cases.slice(0, 5).map(caseKey));
    setRoute(undefined);
    setObservation("");
  }, [review.run_id]);

  const notable = review.notable_cases;
  return <section className="iteration-guide">
    <h2>Improve this benchmark</h2>
    <div className="iteration-guide__thread" aria-live="polite">
      <article className="iteration-guide__turn iteration-guide__turn--assistant">
        <strong>Iteration guide</strong>
        <p>{review.opening}</p>
        <p>This run has {review.counts.failed} failed, {review.counts.error} errored, and {review.counts.missing} missing case trials.</p>
      </article>

      <article className="iteration-guide__turn iteration-guide__turn--assistant">
        <strong>1. Review the evidence</strong>
        {notable.length ? <>
          <p>Select the cases that should anchor the next conversation.</p>
          <div className="iteration-guide__cases">
            {notable.map(row => {
              const key = caseKey(row);
              return <label key={key} className="workspace-check">
                <input type="checkbox" checked={selectedCases.includes(key)} onChange={event => setSelectedCases(event.target.checked ? [...selectedCases, key] : selectedCases.filter(value => value !== key))} />
                <span><strong>{key}</strong> · {row.outcome}{row.error ? ` · ${row.error}` : ""}</span>
              </label>;
            })}
          </div>
        </> : <p>No failed, errored, or missing trials were found. You can still review coverage, scoring, or the expert review plan.</p>}
      </article>

      <article className="iteration-guide__turn iteration-guide__turn--assistant">
        <strong>2. Choose what to reconsider</strong>
        <div className="iteration-guide__routes">
          {review.revision_routes.map(candidate => <button key={candidate.stage} type="button" aria-pressed={route?.stage === candidate.stage} onClick={() => setRoute(candidate)}><strong>{candidate.label}</strong><span>{candidate.purpose}</span></button>)}
        </div>
      </article>

      {route && <article className="iteration-guide__turn iteration-guide__turn--user">
        <strong>Your review</strong>
        <label className="workspace-field">What did you notice?<textarea rows={3} value={observation} onChange={event => setObservation(event.target.value)} placeholder="For example: two urgent cases use ambiguous reference labels, so I want to inspect those labels before changing the scoring rule." /></label>
        <button type="button" className="primary-button" onClick={() => void onRevise(route, iterationPrompt(run, route, selectedCases, observation))}>Continue to {stageNames[route.stage]}</button>
        <p className="workspace-note">ARISEKit will open the owning authoring stage and start the conversation with this run review. The current saved version and its results remain available. Complete the affected stages, save a new version, then rerun it here.</p>
      </article>}

      <article className="iteration-guide__turn iteration-guide__turn--assistant">
        <strong>3. Compare the next run</strong>
        <p>If the benchmark definition is already correct, rerun this saved version. A changed plan is saved as a separate version before it runs.</p>
        <button type="button" onClick={onRerun}>Run this version again</button>
      </article>
    </div>
  </section>;
}

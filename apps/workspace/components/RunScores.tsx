import type { Run } from "../lib/workspaceTypes";

export default function RunScores({ run }: { run: Run }) {
  const { completed, errored } = run.bundle.summary;
  if (completed === 0) {
    return <div role="status" className="workspace-error">
      <h2>No performance result available</h2>
      <p>No case completed with a model response. {errored} case trial(s) ended in an execution error and {run.missing_count} are missing. Repair the run before interpreting model performance.</p>
      <p>Scores and confidence intervals are not shown because execution failures do not establish model accuracy. The original score records remain in the run receipt.</p>
    </div>;
  }
  return <>
    {(errored > 0 || run.missing_count > 0) && <p role="status" className="workspace-error">This evaluation is incomplete: {completed} case trial(s) completed, {errored} ended in errors, and {run.missing_count} are missing. The recorded scores below may include execution failures; inspect their denominators and case outcomes before interpreting performance.</p>}
    <table><caption>Recorded aggregate scores</caption><thead><tr><th>Metric</th><th>Value</th><th>N</th><th>CI half-width</th></tr></thead><tbody>{run.bundle.metrics.map(metric => <tr key={`${metric.category}/${metric.name}`}><td>{metric.category} / {metric.name}</td><td>{metric.value.toFixed(3)}</td><td>{metric.n}</td><td>{metric.ci === null ? "Not calculated" : metric.ci.toFixed(3)}</td></tr>)}</tbody></table>
    <p className="workspace-note">N is the denominator recorded by the scorer, not necessarily the number of successful responses. Scores are shown as recorded; opening this page does not recompute or change the aggregate evidence.</p>
  </>;
}

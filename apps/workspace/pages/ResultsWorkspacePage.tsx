import { useEffect, useRef, useState } from "react";
import VersionBadge from "../shell/VersionBadge";
import "../styles/workspace.css";

import type { IterationRoute, Metric, Job, Workspace } from "../lib/workspaceTypes";
import IterationGuide from "../components/IterationGuide";
import RunScores from "../components/RunScores";

function getToken() {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const token = fragment.get("token");
  if (token) {
    sessionStorage.setItem("arisekit-workspace-token", token);
    window.history.replaceState(null, "", window.location.pathname);
  }
  return token ?? sessionStorage.getItem("arisekit-workspace-token") ?? "";
}

async function api(path: string, payload?: unknown) {
  const response = await fetch(`/api/workspace${path}`, {
    headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
    ...(payload === undefined ? {} : { method: "POST", body: JSON.stringify(payload) }),
    cache: "no-store",
  });
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("Open this page through the local results workspace service.");
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error ?? "Workspace request failed");
  return result;
}

function downloadText(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/octet-stream" }));
  const link = document.createElement("a"); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function download(value: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Answer({ value }: { value: unknown }) {
  if (typeof value === "string") return <p>{value}</p>;
  if (value && typeof value === "object" && "final_response" in value) {
    const trajectory = value as { final_response: unknown; turns: unknown[] };
    return <><p>{String(trajectory.final_response ?? "No final answer")}</p>
      <details><summary>Tool calls and response history</summary><pre>{JSON.stringify(trajectory.turns, null, 2)}</pre></details></>;
  }
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

type Props = {
  imported?: Workspace;
  embedded?: boolean;
  request?: typeof api;
  initialTab?: string;
  onRevise?: (route: IterationRoute, prompt: string) => void | Promise<void>;
};

export default function ResultsWorkspacePage({ imported, embedded = false, request = api, initialTab = "results", onRevise }: Props) {
  const readOnly = imported !== undefined;
  const [workspace, setWorkspace] = useState<Workspace | null>(imported ?? null);
  const [error, setError] = useState("");
  const [exported, setExported] = useState<{ text: string; sha256: string }>();
  const [selectedRun, setSelectedRun] = useState(imported?.runs[0]?.id ?? "");
  const [models, setModels] = useState<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [running, setBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const busy = running || submitting;
  const [confirmPaid, setConfirmPaid] = useState(false);
  const [tab, setTab] = useState(initialTab);
  const pendingOperation = useRef("");
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const Container = embedded ? "div" : "main";
  const Title = embedded ? "h3" : "h1";

  async function refresh() {
    let data: Workspace;
    try { data = await request(""); }
    catch (cause) { setWorkspace(null); throw cause; }
    setWorkspace(data); setJobs(data.operations); setExported(undefined);
    setSelectedRun(current => data.runs.some(run => run.id === current) ? current : (data.runs.find(run => run.kind === "smoke")?.id ?? data.runs[0]?.id ?? ""));
    setModels(current => current.length ? current.filter(model => data.routes.some(route => route.model === model)) : data.routes.slice(0, 1).map(route => route.model));
  }

  useEffect(() => {
    if (readOnly) return;
    request("/jobs").then(async (current: Job[]) => {
      setJobs(current);
      if (current.some(job => job.status === "running")) setBusy(true);
      else await refresh();
    }).catch(cause => setError(String(cause.message)));
  }, []);

  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current: Job[] = await request("/jobs");
        if (cancelled) return;
        setJobs(current);
        if (current.every(job => job.status !== "running")) {
          setBusy(false); await refresh();
          if (embedded && ["smoke", "sweep"].includes(pendingOperation.current)) setTab(onRevise ? "review" : "results");
        } else timer = setTimeout(poll, 1000);
      } catch (cause) {
        if (!cancelled) { setError((cause as Error).message); timer = setTimeout(poll, 3000); }
      }
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [running]);

  useEffect(() => {
    if (tab !== "review") return;
    const frame = requestAnimationFrame(() => workspaceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    return () => cancelAnimationFrame(frame);
  }, [tab]);

  async function run(operation: string, payload: unknown) {
    setError(""); setSubmitting(true); pendingOperation.current = operation;
    try { await request(`/${operation}`, payload); setBusy(true); }
    catch (cause) { setError((cause as Error).message); setBusy(false); }
    finally { setSubmitting(false); }
  }

  const runRecord = workspace?.runs.find(row => row.id === selectedRun);
  const summary = runRecord?.bundle.summary;
  return <div ref={workspaceRef} className={`results-workspace${embedded ? " results-workspace--embedded" : ""}`}>
    {!embedded && <header className="workspace-top"><strong>ARISEKit</strong><span>Results workspace</span><span>{readOnly ? "Imported evidence" : `${workspace?.worker.kind ?? "Local"} worker`}</span></header>}
    <Container>
      <div className="workspace-title"><div><Title>{workspace?.name ?? "Open your benchmark results"}</Title>
        <p>Review the evidence, return to the plan, and repeat your evaluation.</p></div>
        {!readOnly && <button disabled={busy} onClick={() => { setError(""); void refresh().catch(cause => setError(cause.message)); }}>Refresh evidence</button>}
      </div>
      {error && <div role="alert" className="workspace-error">{error}</div>}
      {!workspace && (embedded ? <p role="status">{running ? "Evaluation in progress…" : "Loading this benchmark version…"}</p> : <p role="status">{error ? "Open the launch URL printed by your local runner." : "Loading benchmark results…"}</p>)}
      {workspace && <>
        <p className="workspace-evidence">{embedded ? <>Saved plan and run files verified. Status: <strong>{workspace.readiness}</strong>.</> : <>{readOnly ? "Export checksum and originating plan verified. Package verification was performed by the exporting worker." : "Plan, package, run manifest, checkpoint, and score hashes verified."} Package readiness: <strong>{workspace.readiness}</strong>. This describes the package, not whether the selected run succeeded.</>}</p>
        <nav className="workspace-tabs" aria-label="Workspace sections">{(readOnly ? ["results", "plan"] : ["results", "plan", "iterate", ...(embedded && onRevise && workspace.runs.length ? ["review"] : [])]).map(value => <button key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>{value === "iterate" ? (embedded ? "Run benchmark" : "Guided execution") : value === "review" ? "Improve benchmark" : value === "plan" ? "Source plan" : value === "execute" ? "Guided execution" : "Run results"}</button>)}</nav>
        {tab === "results" && <section>
          <label className="workspace-field">Retained run<select value={selectedRun} onChange={event => setSelectedRun(event.target.value)}>{workspace.runs.map(record => <option key={record.id} value={record.id}>{record.bundle.model} · {record.kind === "smoke" ? "Original smoke evidence" : "Latest run / resume"} · {record.bundle.run_manifest_digest.slice(0, 8)}</option>)}</select></label>
          {!runRecord && <p>No completed runs yet. Open Run benchmark to start this version.</p>}
          {runRecord && summary && <>
            <dl className="workspace-metrics"><div><dt>Completed</dt><dd>{summary.completed}</dd></div><div><dt>Errors</dt><dd>{summary.errored}</dd></div><div><dt>Reused on resume</dt><dd>{summary.skipped}</dd></div><div><dt>Recorded cost</dt><dd>{summary.cost_unknown ? "Unknown" : `$${summary.cost_total.toFixed(5)}`}</dd></div><div><dt>Accounted calls</dt><dd>{summary.calls_total}</dd></div></dl>
            <p className="workspace-note">Cost and call totals include retained work. They are not new charges for opening or resuming a run. Cost is recorded model accounting, not an invoice.</p>
            {(summary.budget_exhausted || summary.call_budget_exhausted || summary.cost_bound_exceeded) && <p role="status">This run reached a cost or call limit. Review case errors and missing trials before interpreting its scores.</p>}
            <RunScores run={runRecord} />
            <p>{runRecord.expected_count} planned case trials; {runRecord.missing_count} missing. Package readiness: {workspace.readiness}. Case scores below are recomputed by the worker using the package’s deterministic scorer.</p><h2>Case results</h2>{runRecord.cases.map(row => <article className="workspace-case" key={`${row.id}/${row.trial}`}><h3>{row.id} <small>Trial {row.trial}</small></h3><p><strong>{row.outcome}</strong>{!row.error && row.metrics.map(metric => <span key={`${metric.category}/${metric.name}`}> · {metric.name}: {metric.value}</span>)}</p><p>Recorded case cost: {row.metadata.cost_known === true && typeof row.metadata.cost === "number" ? `$${row.metadata.cost.toFixed(5)}` : "Unknown"}</p><p>{row.prompt}</p>{row.error ? <p role="alert">{row.error}</p> : <Answer value={row.response} />}<details><summary>Usage, attempts, and errors</summary><pre>{JSON.stringify(row.metadata, null, 2)}</pre></details><details><summary>Expected outcome</summary><pre>{JSON.stringify(row.expected, null, 2)}</pre></details></article>)}
            <details><summary>Provenance and run receipt</summary><p>Build specification: <code>{workspace.build_spec_sha256}</code></p><pre>{JSON.stringify(runRecord.bundle, null, 2)}</pre></details>
            {!readOnly && <><button disabled={busy} onClick={() => void api("/export").then(setExported).catch(cause => setError(cause.message))}>Prepare result export</button>{exported && <div><p>Save both files together. SHA-256: <code>{exported.sha256}</code></p><button onClick={() => downloadText(exported.text, "result-bundle.json")}>Download result bundle</button>{" "}<button onClick={() => downloadText(exported.sha256 + "\n", "result-bundle.json.sha256")}>Download checksum receipt</button></div>}</>}
          </>}
        </section>}
        {tab === "plan" && <section><h2>The plan that produced this package</h2><p>The selected plan matches the package’s recorded build-specification digest. All seven artifact hashes are checked when the workspace loads.</p>{workspace.artifacts.map(artifact => <details key={artifact.role} className="workspace-plan"><summary>{artifact.role.replaceAll("-", " ")}</summary><pre>{artifact.text}</pre><small>SHA-256: {artifact.sha256}</small></details>)}<details><summary>Complete build specification</summary><pre>{JSON.stringify(workspace.plan, null, 2)}</pre></details></section>}
        
        {tab === "review" && runRecord && onRevise && <IterationGuide run={runRecord} onRevise={onRevise} onRerun={() => setTab("iterate")} />}
        {tab === "iterate" && <section><h2>{embedded ? "Run benchmark" : "Guided execution"}</h2>
          <div className="workspace-action"><h3>1. Check the worker</h3><p>Connected to the {workspace.worker.kind} worker. Model credentials stay in its environment.</p>{workspace.routes.some(route => route.model.startsWith("azure/")) && <p>Azure configuration: {workspace.worker.azure_missing.length ? `Missing ${workspace.worker.azure_missing.join(", ")}` : "Environment configured; endpoint connectivity is checked when the run starts."}</p>}</div>
          <div className="workspace-action"><h3>2. Run the planned smoke test</h3><p>{workspace.smoke_test.model} · up to {workspace.smoke_test.limit} cases · {workspace.smoke_test.trials} trial(s). Status: {workspace.smoke_test.status}.</p>{workspace.readiness === "awaiting_smoke_test" && <><label className="workspace-check"><input type="checkbox" checked={confirmPaid} disabled={busy} onChange={event => setConfirmPaid(event.target.checked)} />I reviewed the planned smoke request and its limits; provider routes may incur costs.</label><button disabled={busy || !confirmPaid} onClick={() => { setConfirmPaid(false); void run("smoke", { confirm_paid: true }); }}>{embedded ? "Run this benchmark" : "Start planned smoke run"}</button></>}{workspace.readiness === "blocked" && <p>The smoke run failed. Inspect its errors and repair or revise the package through the CLI before continuing.</p>}</div>
          <h3>3. Preview and run reviewed routes</h3><p>Operations use this saved package and its reviewed settings. Receipts are saved in its results directory.</p>
          <fieldset disabled={busy}><legend>Models from the reviewed plan</legend>{workspace.routes.map(route => <label key={route.model} className="workspace-check"><input type="checkbox" checked={models.includes(route.model)} onChange={event => { setConfirmPaid(false); setModels(event.target.checked ? [...models, route.model] : models.filter(model => model !== route.model)); }} />{route.model} · {route.trials} trial{route.trials === 1 ? "" : "s"}</label>)}</fieldset>
          {workspace.routes.length === 1 && <p>Only one model is approved in this plan. Add further routes through a reviewed plan revision before a multi-model sweep.</p>}
          <p>Completion limit: {workspace.runner.max_tokens ?? "not set"} tokens. Runner budget: {workspace.runner.max_cost === null ? "not set" : `$${workspace.runner.max_cost}`}. Call limit: {workspace.runner.max_calls ?? "not set"}. Item selection follows the planned smoke limit.</p>
          <div className="workspace-action"><h3>Cost preview</h3><p>Estimate the first selected route without inference. Unknown costs and budget limitations remain visible in the receipt.</p><button disabled={busy || !models.length} onClick={() => void run("preview", { model: models[0] })}>Preview cost · no model calls</button></div>
          <div className="workspace-action"><h3>Re-score retained responses</h3><p>Apply the package’s current deterministic scorer to the selected run. This writes a scoring revision without calling a model. Changing rubric or case conditions requires a reviewed package revision.</p><label className="workspace-field">Run to re-score<select value={selectedRun} onChange={event => setSelectedRun(event.target.value)}>{workspace.runs.map(record => <option key={record.id} value={record.id}>{record.bundle.model} · {record.kind} · {record.bundle.run_manifest_digest.slice(0, 8)}</option>)}</select></label><button disabled={busy || !selectedRun} onClick={() => void run("rescore", { run_id: selectedRun })}>Re-score · no model calls</button></div>
          <div className="workspace-action"><h3>Run or resume a sweep</h3><p>Run the selected routes using the engine’s existing checkpoint behavior. Changed runtime identities may start a new run. Agentic budgets are checked between trajectories; they are not a hard per-turn spending cap.</p><label className="workspace-check"><input type="checkbox" checked={confirmPaid} disabled={busy} onChange={event => setConfirmPaid(event.target.checked)} />I have reviewed the selected routes and limits; this operation may make paid model calls.</label><button disabled={busy || !models.length || !confirmPaid || workspace.readiness !== "ready"} onClick={() => { setConfirmPaid(false); void run("sweep", { models, confirm_paid: true }); }}>Run / resume selected sweep</button></div>
        </section>}
        {!readOnly && <section aria-live="polite"><h2>Workspace operations</h2>{busy && <p role="status">The runtime is working. This page will refresh when the operation finishes.</p>}{!jobs.length && <p>No operations started in this session.</p>}{jobs.slice().reverse().map(job => <article className="workspace-operation" key={job.id}><h3>{job.operation} · {job.status}</h3>{job.error && <p role="alert">{job.error}</p>}{job.result !== undefined && <><Receipt result={job.result} /><details><summary>Full operation receipt</summary><pre>{JSON.stringify(job.result, null, 2)}</pre></details><button onClick={() => download(job.result, `${job.operation}-receipt.json`)}>Download receipt</button></>}</article>)}</section>}
        {!embedded && <footer>These results describe this benchmark and run. Execution readiness does not establish clinical validity or MAST admission.</footer>}
      </>}
    </Container>{!embedded && <VersionBadge />}
  </div>;
}

function Receipt({ result }: { result: unknown }) {
  const value = result as { blockers?: { code: string; message: string }[]; metrics?: Metric[]; cost?: { nominal_upper_bound_usd?: string | null }; revision_digest?: string; cells?: { model: string; status: string; completed: number; errored: number; cost: number; error: string | null }[] };
  return <div>{value.cost && <p>Nominal cost upper bound: {value.cost.nominal_upper_bound_usd == null ? "Unknown" : `$${value.cost.nominal_upper_bound_usd}`}</p>}{value.blockers && value.blockers.length > 0 && <><p>Cost preview has limitations:</p><ul>{value.blockers.map(blocker => <li key={blocker.code}>{blocker.message || blocker.code}</li>)}</ul></>}{value.revision_digest && <p>Scoring revision saved: <code>{value.revision_digest.slice(0, 12)}</code></p>}{value.metrics?.map(metric => <p key={`${metric.category}/${metric.name}`}>{metric.name}: {metric.value} (n={metric.n})</p>)}{value.cells && <table><caption>Sweep outcomes</caption><thead><tr><th>Model</th><th>Status</th><th>Completed</th><th>Errors</th></tr></thead><tbody>{value.cells.map(cell => <tr key={cell.model}><td>{cell.model}</td><td>{cell.status}</td><td>{cell.completed}</td><td>{cell.errored}</td></tr>)}</tbody></table>}</div>;
}

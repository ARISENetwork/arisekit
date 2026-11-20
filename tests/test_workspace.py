import json
import shutil
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, parse_qs
from unittest.mock import Mock

import pytest

from arisekit import cli
from arisekit.workspace import ResultsWorkspace, make_server


@pytest.fixture
def workspace(tmp_path):
    authoring = tmp_path / "authoring"
    shutil.copytree(Path(__file__).parents[1] / "examples/agentic-fhir-golden-path/authoring", authoring)
    benchmarks, results = tmp_path / "benchmarks", tmp_path / "results"
    common = ["--benchmarks-dir", str(benchmarks), "--results-dir", str(results)]
    assert cli.main([*common, "new-benchmark", "--spec", str(authoring / "benchmark-build-spec.json")]) == 0
    assert cli.main([*common, "eval", "agentic-fhir-golden-path", "--model", "stub/reference", "--limit", "2", "--trials", "1"]) == 0
    return ResultsWorkspace(benchmarks / "agentic-fhir-golden-path", authoring, results)


def test_import_binds_plan_cases_and_real_engine_operations(workspace, monkeypatch):
    import litellm
    no_calls = Mock(side_effect=AssertionError("unexpected paid inference"))
    monkeypatch.setattr(litellm, "completion", no_calls)
    snapshot = workspace.snapshot()
    assert len(snapshot["artifacts"]) == 7
    assert len(snapshot["runs"][0]["cases"]) == 2
    assert snapshot["runs"][0]["iteration_review"]["schema_version"] == "arisekit.iteration-review.v1"
    assert snapshot["runs"][0]["iteration_review"]["counts"]["passed"] == 2
    assert [route["stage"] for route in snapshot["runs"][0]["iteration_review"]["revision_routes"]] == [
        "data-intake", "rubric-design", "study-design",
    ]
    assert snapshot["runs"][0]["cases"][0]["expected"]["schema_version"] == "arisekit.agentic-pass-condition.v1"
    preview = workspace.execute("preview", {"model": "stub/reference"})
    assert preview["no_model_calls_made"]
    revision = workspace.execute("rescore", {"run_id": snapshot["runs"][0]["id"]})
    assert revision["schema_version"] == "arisekit.scoring-revision.v1"
    sweep = workspace.execute("sweep", {"models": ["stub/reference"], "confirm_paid": True})
    assert sweep["cells"][0]["status"] == "succeeded"
    assert sweep["cells"][0]["completed"] == 2
    no_calls.assert_not_called()


@pytest.mark.parametrize("mutation", ["plan", "artifact", "checkpoint", "scores", "manifest"])
def test_import_rejects_modified_evidence(workspace, mutation):
    snapshot = workspace.snapshot()
    if mutation == "plan":
        path = workspace.authoring / "benchmark-build-spec.json"
    elif mutation == "artifact":
        path = workspace.authoring / "study-plan.md"
    elif mutation == "manifest":
        path = workspace.benchmark / "package/env.json"
    else:
        artifact = "raw_checkpoint" if mutation == "checkpoint" else "scores"
        path = workspace.results / snapshot["runs"][0]["bundle"][artifact]["path"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        workspace.snapshot()


@pytest.mark.parametrize("operation,payload", [
    ("preview", {"model": "azure/unreviewed"}),
    ("preview", {"model": "stub/reference", "max_tokens": 999999}),
    ("rescore", {"run_id": "../../outside.jsonl"}),
    ("sweep", {"models": ["azure/unreviewed"], "confirm_paid": True}),
    ("sweep", {"models": ["stub/reference"], "confirm_paid": False}),
    ("sweep", {"models": ["stub/reference", "stub/reference"], "confirm_paid": True}),
    ("shell", {"command": "echo wrong"}),
])
def test_actions_cannot_expand_the_imported_plan(workspace, operation, payload):
    with pytest.raises(ValueError):
        workspace.execute(operation, payload)


def test_only_one_operation_can_run_at_a_time(workspace, monkeypatch):
    started, finish = threading.Event(), threading.Event()
    def execute(*args):
        started.set()
        finish.wait(5)
        return {"ok": True}
    monkeypatch.setattr(workspace, "execute", execute)
    identifier = workspace.submit("preview", {"model": "stub/reference"})
    assert started.wait(2)
    try:
        with pytest.raises(ValueError, match="already running"):
            workspace.submit("preview", {"model": "stub/reference"})
        assert workspace.jobs[identifier]["status"] == "running"
    finally:
        finish.set()


def test_http_requires_launch_token_and_same_origin(workspace, tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html>workspace</html>")
    server, url = make_server(workspace, ui, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    parsed = urlsplit(url)
    endpoint = f"http://{parsed.netloc}/api/workspace"
    token = parse_qs(parsed.fragment)["token"][0]
    try:
        for headers in [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Bearer {token}", "Origin": "https://other.example"}, {"Authorization": f"Bearer {token}", "Host": "rebind.example"}]:
            with pytest.raises(HTTPError) as error:
                urlopen(Request(endpoint, headers=headers), timeout=3)
            assert error.value.code == 403
        with urlopen(Request(endpoint, headers={"Authorization": f"Bearer {token}"}), timeout=3) as response:
            value = json.load(response)
        assert value["readiness"] == "ready"
        with pytest.raises(HTTPError) as error:
            urlopen(Request(endpoint + "/sweep", data=b'{}', headers={"Content-Type": "application/json"}), timeout=3)
        assert error.value.code == 403
        with urlopen(url.split("#")[0], timeout=3) as response:
            assert b"workspace" in response.read()
    finally:
        server.shutdown()
        server.server_close()


def test_failed_sweep_is_visible_and_history_survives_restart(workspace, monkeypatch):
    monkeypatch.setattr(workspace, "execute", lambda *args: {"cells": [{"model": "stub/reference", "status": "failed"}]})
    identifier = workspace.submit("sweep", {"models": ["stub/reference"], "confirm_paid": True})
    deadline = time.monotonic() + 3
    while workspace.active is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert workspace.jobs[identifier]["status"] == "failed"
    restored = ResultsWorkspace(workspace.benchmark, workspace.authoring, workspace.results)
    assert restored.jobs[identifier]["status"] == "failed"
    assert restored.jobs[identifier]["result"]["cells"][0]["status"] == "failed"


def test_portable_export_contains_exact_evidence_and_plan(workspace):
    import hashlib
    from arisekit.workspace_bundle import export_bundle
    exported = export_bundle(workspace)
    assert hashlib.sha256(exported["text"].encode()).hexdigest() == exported["sha256"]
    payload = json.loads(exported["text"])
    assert payload["schema_version"] == "arisekit.workspace-export.v1"
    assert hashlib.sha256(payload["build_spec_text"].encode()).hexdigest() == payload["workspace"]["build_spec_sha256"]
    assert payload["workspace"]["operations"] == []
    for relative, artifact in payload["evidence"].items():
        assert artifact["text"].encode() == (workspace.results / relative).read_bytes()
        assert hashlib.sha256(artifact["text"].encode()).hexdigest() == artifact["sha256"]
    cases = payload["workspace"]["runs"][0]["cases"]
    assert all(case["outcome"] == "passed" for case in cases)
    assert all(case["metrics"][0]["value"] == 1 for case in cases)
    assert all(case["response"]["turns"] for case in cases)


def test_guided_smoke_advances_new_package_without_provider_calls(tmp_path, monkeypatch):
    import litellm
    no_calls = Mock(side_effect=AssertionError("unexpected paid inference"))
    monkeypatch.setattr(litellm, "completion", no_calls)
    authoring = Path(__file__).parents[1] / "examples/agentic-fhir-golden-path/authoring"
    benchmarks = tmp_path / "benchmarks"
    assert cli.main(["--benchmarks-dir", str(benchmarks), "new-benchmark", "--spec", str(authoring / "benchmark-build-spec.json")]) == 0
    workspace = ResultsWorkspace(benchmarks / "agentic-fhir-golden-path", authoring, tmp_path / "results")
    assert workspace.snapshot()["readiness"] == "awaiting_smoke_test"
    assert workspace.snapshot()["runs"] == []
    with pytest.raises(ValueError, match="explicitly"):
        workspace.execute("smoke", {"confirm_paid": False})
    with pytest.raises(ValueError):
        workspace.execute("smoke", {"confirm_paid": True, "model": "unreviewed"})
    result = workspace.execute("smoke", {"confirm_paid": True})
    assert result["readiness"] == "ready"
    assert workspace.snapshot()["runs"][0]["missing_count"] == 0
    with pytest.raises(ValueError, match="already been recorded"):
        workspace.execute("smoke", {"confirm_paid": True})
    no_calls.assert_not_called()


@pytest.mark.parametrize("mutation", ["count", "metric", "cost"])
def test_workspace_rejects_receipt_claims_that_disagree_with_sources(workspace, mutation):
    snapshot = workspace.snapshot()
    run = next(row for row in snapshot["runs"] if row["kind"] == "latest")
    bundle = run["bundle"]
    if mutation == "count": bundle["summary"]["completed"] += 1
    elif mutation == "metric": bundle["metrics"][0]["value"] = 0.123
    else: bundle["summary"]["cost_total"] = 99
    (workspace.results / run["id"]).write_text(json.dumps(bundle))
    with pytest.raises(ValueError): workspace.snapshot()


def test_evidence_symlinks_rejected_even_inside_results(workspace):
    run = workspace.snapshot()["runs"][0]
    path = workspace.results / run["bundle"]["raw_checkpoint"]["path"]
    target = path.with_suffix(".saved")
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError): workspace.snapshot()


def test_azure_preflight_reports_names_only(monkeypatch):
    from arisekit.workspace import _check_runtime, _azure_missing
    for name in ("AZURE_API_BASE", "AZURE_API_VERSION", "AZURE_API_KEY", "AZURE_AD_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="AZURE_API_BASE"):
        _check_runtime(["azure/reviewed-deployment"])
    monkeypatch.setenv("AZURE_API_BASE", "https://example.invalid")
    monkeypatch.setenv("AZURE_API_VERSION", "test-version")
    monkeypatch.setenv("AZURE_AD_TOKEN", "secret-value")
    assert _azure_missing() == []
    _check_runtime(["azure/reviewed-deployment"])



@pytest.mark.parametrize("state", ["missing", "error"])
def test_partial_and_failed_case_outcomes_remain_visible(tmp_path, state):
    from arisekit.scaffold import load_scaffolded_benchmark
    from arisekit.workspace_bundle import export_bundle
    from arisekit.run_inspection import write_run_inspection
    from arisekit.types import Metric
    authoring = Path(__file__).parents[1] / "examples/p0-golden-path/authoring"
    benchmarks = tmp_path / "benchmarks"
    assert cli.main(["--benchmarks-dir", str(benchmarks), "new-benchmark", "--spec", str(authoring / "benchmark-build-spec.json")]) == 0
    workspace = ResultsWorkspace(benchmarks / "p0-golden-path", authoring, tmp_path / "results")
    bench = load_scaffolded_benchmark(workspace.benchmark)
    result = bench.run("stub/reference", limit=2, trials=1, results_dir=workspace.results, auto_manifest=True)
    scores = workspace.results / json.loads(result.bundle_path.read_text())["scores"]["path"]
    # Retain a controlled partial or failed response fixture under the real
    # engine manifest, then generate a consistent receipt using its writer.
    if state == "missing":
        result.raw = result.raw[:1]
    else:
        result.raw[1].error = "Fixture transport failure"
        result.raw[1].response = None
    result.summary.completed = 1
    result.summary.errored = int(state == "error")
    result.metrics = [Metric(name="accuracy", value=1, n=1)]
    result.summary.output_path.write_text("".join(json.dumps(row.to_dict()) + "\n" for row in result.raw))
    result.to_csv(scores)
    write_run_inspection(result, scores_path=scores, results_root=workspace.results)
    snapshot = workspace.snapshot()
    assert snapshot["readiness"] == "awaiting_smoke_test"
    assert snapshot["runs"][0]["missing_count"] == int(state == "missing")
    assert snapshot["runs"][0]["cases"][1]["outcome"] == state
    review = snapshot["runs"][0]["iteration_review"]
    assert review["counts"][state] == 1
    assert review["notable_cases"][0]["outcome"] == state
    assert export_bundle(workspace)["sha256"]

"""Opt-in test of the authored package through the public CLI and Azure."""

import hashlib
import json
import os
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from arisekit import cli
from arisekit.package import load_package
from arisekit.run_inspection import load_and_verify_run_inspection
from arisekit.runnable import load_manifest
from live_smoke_config import client_options, live_enabled


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not live_enabled(os.environ), reason="set ARISEKIT_LIVE=1 explicitly"),
]
MODEL = "azure/gpt-5-mini"
SLUG = "azure-fhir-authoring"


def test_plan_to_package_to_azure_and_portable_resume(tmp_path, monkeypatch, record_property):
    import litellm

    client_options(MODEL, os.environ)
    source = Path(__file__).resolve().parents[1] / "examples" / SLUG / "authoring"
    authoring = tmp_path / "authoring"
    shutil.copytree(source, authoring)
    benchmarks, results = tmp_path / "benchmarks", tmp_path / "results"
    common = ["--benchmarks-dir", str(benchmarks), "--results-dir", str(results)]
    calls = []
    completion = litellm.completion

    def bounded_completion(**kwargs):
        assert kwargs["model"] == MODEL
        assert len(calls) < 6, "authoring test exceeded six model calls"
        assert "temperature" not in kwargs
        assert kwargs["max_tokens"] == 1024
        calls.append(kwargs["model"])
        return completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", bounded_completion)
    assert cli.main([*common, "new-benchmark", "--spec", str(authoring / "benchmark-build-spec.json")]) == 0
    root = benchmarks / SLUG
    manifest_path = root / "runnable-benchmark.json"
    assert load_manifest(manifest_path).readiness == "awaiting_smoke_test"
    assert cli.main([*common, "check-benchmark", SLUG, "--verify-linked-provenance"]) == 0
    assert not calls
    package = load_package(root / "package", verify_assets=True)
    assert len(package.cohort) == 2
    assert "fhir_bundle" not in (root / "package/cases.jsonl").read_text()

    command = [*common, "eval", SLUG, "--model", MODEL, "--limit", "2", "--trials", "1"]
    try:
        assert cli.main(command) == 0
    finally:
        record_property("provider_calls", len(calls))
        record_property("model_route", MODEL)
    runnable = load_manifest(manifest_path)
    assert runnable.readiness == "ready"
    assert runnable.smoke_test.status == "passed"
    bundle_path = results / runnable.smoke_test.result_bundle_path
    bundle = load_and_verify_run_inspection(bundle_path, results_root=results)
    assert hashlib.sha256(bundle_path.read_bytes()).hexdigest() == runnable.smoke_test.result_bundle_sha256
    assert bundle["summary"]["completed"] == 2
    assert bundle["summary"]["errored"] == 0
    assert not bundle["summary"]["cost_unknown"]
    assert not bundle["summary"]["budget_exhausted"]
    assert 0 < bundle["summary"]["cost_total"] < 0.02
    assert bundle["metrics"][0]["value"] == 1.0
    assert bundle["metrics"][0]["n"] == 2
    assert 4 <= len(calls) <= 6
    record_property("recorded_cost_usd", bundle["summary"]["cost_total"])
    (tmp_path / "first-run-results.json").write_bytes(bundle_path.read_bytes())
    raw = results / bundle["raw_checkpoint"]["path"]
    checkpoint = raw.read_bytes()

    portable = tmp_path / "portable"
    shutil.copytree(root, portable / SLUG)
    shutil.rmtree(authoring)
    shutil.rmtree(benchmarks)
    portable_common = ["--benchmarks-dir", str(portable), "--results-dir", str(results)]
    assert cli.main([*portable_common, "check-benchmark", SLUG]) == 0
    no_inference = Mock(side_effect=AssertionError("completed evaluation dispatched again"))
    monkeypatch.setattr(litellm, "completion", no_inference)
    assert cli.main([*portable_common, "eval", SLUG, "--model", MODEL, "--limit", "2", "--trials", "1"]) == 0
    no_inference.assert_not_called()
    assert raw.read_bytes() == checkpoint
    latest = next(results.glob("run-results/**/run-results.json"))
    resumed = load_and_verify_run_inspection(latest, results_root=results)
    assert resumed["summary"]["skipped"] == 2
    assert resumed["metrics"] == bundle["metrics"]
    portable_manifest = load_manifest(portable / SLUG / "runnable-benchmark.json")
    evidence = results / portable_manifest.smoke_test.result_bundle_path
    assert hashlib.sha256(evidence.read_bytes()).hexdigest() == portable_manifest.smoke_test.result_bundle_sha256
    record_property("resume_provider_calls", 0)

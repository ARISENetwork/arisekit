"""Vertical contract tests for build-spec v2 agentic/FHIR authoring."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from arisekit import cli
from arisekit.client import REFERENCE_STUB_MODEL
from arisekit.package import PackageAssetManifest, load_package
from arisekit.runnable import load_manifest as load_runnable_manifest
from arisekit.scaffold import (
    AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION,
    BenchmarkScaffoldSpec,
    ScaffoldSpecError,
    check_benchmark,
    scaffold_benchmark,
)
from arisekit.types import Trajectory


ARTIFACT_ROLES = (
    "need-statement",
    "existing-coverage",
    "compliance-scope",
    "data-profile",
    "rubric",
    "study-plan",
    "implementation-plan",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _bundle(case_id: str, patient_id: str, family: str) -> dict[str, object]:
    return {
        "resourceType": "Bundle",
        "id": case_id,
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": patient_id,
                    "name": [{"family": family}],
                }
            }
        ],
    }


def _fixture(root: Path) -> tuple[Path, dict[str, object]]:
    root.mkdir(parents=True)
    artifacts: list[dict[str, str]] = []
    for role in ARTIFACT_ROLES:
        path = root / f"{role}.md"
        path.write_text(f"# {role}\nAccepted synthetic fixture.\n", encoding="utf-8")
        artifacts.append({"role": role, "path": path.name, "sha256": _sha256(path)})

    rows = [
        {
            "case_id": "patient-one",
            "prompt": "Use get_patient for Patient/p1 and report the family name.",
            "pass_condition": {
                "schema_version": "arisekit.agentic-pass-condition.v1",
                "required_tool_calls": [
                    {"name": "get_patient", "arguments": {"patient_id": "p1"}}
                ],
                "final_response_contains": ["Hernandez"],
            },
            "service": "primary-care",
            "fhir_bundle": _bundle("patient-one", "p1", "Hernandez"),
        },
        {
            "case_id": "patient-two",
            "prompt": "Use get_patient for Patient/p2 and report the family name.",
            "pass_condition": {
                "schema_version": "arisekit.agentic-pass-condition.v1",
                "required_tool_calls": [
                    {"name": "get_patient", "arguments": {"patient_id": "p2"}}
                ],
                "final_response_contains": ["Okafor"],
            },
            "service": "primary-care",
            "fhir_bundle": _bundle("patient-two", "p2", "Okafor"),
        },
    ]
    source = root / "cases.synthetic.jsonl"
    source.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    prompt = "Use only the allowed FHIR tools before answering."
    payload: dict[str, object] = {
        "schema_version": AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION,
        "benchmark": {
            "name": "Synthetic FHIR lookup",
            "slug": "synthetic-fhir-lookup",
            "version": "0.1.0",
            "description": "A portable synthetic Agentic/FHIR fixture.",
            "mast_category": "agentic",
            "mast_compatible": True,
            "modality": "agentic-fhir",
        },
        "source": {
            "kind": "jsonl",
            "path": source.name,
            "sha256": _sha256(source),
            "field_map": {
                "id": "case_id",
                "prompt": "prompt",
                "ground_truth": "pass_condition",
                "metadata": {"specialty": "service"},
                "attachments": None,
                "fhir_bundle": "fhir_bundle",
            },
            "system_prompt": {
                "text": prompt,
                "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
        },
        "scorer": {
            "kind": "pass-at-one",
            "primitive": "arisekit.agentic.PassAtOneScorer",
            "options": {
                "name": "pass_at_1",
                "condition_schema": "arisekit.agentic-pass-condition.v1",
            },
        },
        "agentic": {
            "environment": {
                "kind": "fhir-r4-in-memory",
                "primitive": "arisekit.env.fhir.FHIREnvironment",
                "fhir_version": "R4",
                "isolation": "per-item-trial",
            },
            "tool_catalog": "arisekit.fhir-tools.v1",
            "allowed_tools": ["get_patient"],
            "max_turns": 3,
        },
        "runner": {
            "trials": 1,
            "threads": 2,
            "max_retries": 1,
            "retry_backoff": 0.0,
            "temperature": 0.0,
            "max_tokens": 256,
            "max_cost": None,
            "max_cost_per_call": None,
            "require_known_cost": True,
            "max_calls": None,
        },
        "smoke_test": {"model": REFERENCE_STUB_MODEL, "limit": 2, "trials": 1},
        "first_sweep": [
            {"model": REFERENCE_STUB_MODEL, "provider": "stub", "trials": 1}
        ],
        "artifacts": artifacts,
        "readiness": {
            "status": "ready",
            "data_profile": "materialized",
            "allowed_model_routes": [REFERENCE_STUB_MODEL],
            "library_gaps": [],
            "open_questions": [],
            "user_confirmation": {
                "actor": "fixture author",
                "confirmed_at": "2026-09-02T12:00:00Z",
                "text": "This is the intended synthetic agentic benchmark.",
            },
        },
        "data_governance": {
            "classification": "synthetic",
            "release_posture": "public",
            "materialization_authorization": {
                "authorized": True,
                "actor": "fixture steward",
                "confirmed_at": "2026-09-02T12:01:00Z",
                "text": "I authorize this synthetic fixture to be materialized.",
            },
        },
    }
    spec_path = root / "benchmark-build-spec.json"
    _write_json(spec_path, payload)
    return spec_path, payload


def test_v2_plan_materializes_bound_fhir_package(tmp_path: Path) -> None:
    spec_path, payload = _fixture(tmp_path / "authoring")
    spec = BenchmarkScaffoldSpec.from_json(spec_path)
    assert spec.to_dict() == payload

    receipt = scaffold_benchmark(spec, output_root=tmp_path / "benchmarks")
    package = load_package(receipt.package_path, verify_assets=True)

    assert [path.name for path in package.cohort] == [
        "patient-one.fhir.json",
        "patient-two.fhir.json",
    ]
    assert package.env is not None
    assert package.env["case_bindings"] == {
        "patient-one": "cohort/patient-one.fhir.json",
        "patient-two": "cohort/patient-two.fhir.json",
    }
    assert [tool["name"] for tool in package.env["tools"]] == ["get_patient"]
    cases = (receipt.package_path / "cases.jsonl").read_text(encoding="utf-8")
    assert "fhir_bundle" not in cases
    assert check_benchmark(receipt.root, verify_linked_provenance=True).compatible


def test_v2_cli_smoke_advances_runnable_to_ready(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "authoring")
    benchmarks = tmp_path / "benchmarks"
    results = tmp_path / "results"
    common = ["--benchmarks-dir", str(benchmarks), "--results-dir", str(results)]

    assert cli.main([*common, "new-benchmark", "--spec", str(spec_path)]) == 0
    assert cli.main(
        [
            *common,
            "check-benchmark",
            "synthetic-fhir-lookup",
            "--verify-linked-provenance",
        ]
    ) == 0
    assert cli.main(
        [
            *common,
            "eval",
            "synthetic-fhir-lookup",
            "--model",
            REFERENCE_STUB_MODEL,
            "--limit",
            "2",
            "--trials",
            "1",
        ]
    ) == 0

    runnable = load_runnable_manifest(
        benchmarks / "synthetic-fhir-lookup" / "runnable-benchmark.json"
    )
    assert runnable.readiness == "ready"
    assert runnable.smoke_test.status == "passed"
    run_rows = list(results.glob("raw/synthetic-fhir-lookup/**/*.jsonl"))
    assert run_rows
    payloads = [
        json.loads(line)
        for path in run_rows
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and '"kind": "checkpoint"' not in line
    ]
    assert any(
        isinstance(row.get("response"), dict)
        and row["response"].get("kind") == "trajectory"
        for row in payloads
    )


def test_checked_in_fixture_reaches_ready_without_bespoke_code(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    source = repository / "examples" / "agentic-fhir-golden-path"
    fixture = tmp_path / "fixture"
    shutil.copytree(source, fixture)
    authoring = fixture / "authoring"
    assert not list(fixture.rglob("*.py"))

    benchmarks = tmp_path / "benchmarks"
    results = tmp_path / "results"
    common = ["--benchmarks-dir", str(benchmarks), "--results-dir", str(results)]
    assert cli.main(
        [
            *common,
            "new-benchmark",
            "--spec",
            str(authoring / "benchmark-build-spec.json"),
        ]
    ) == 0
    assert cli.main(
        [
            *common,
            "check-benchmark",
            "agentic-fhir-golden-path",
            "--verify-linked-provenance",
        ]
    ) == 0
    assert cli.main(
        [
            *common,
            "eval",
            "agentic-fhir-golden-path",
            "--model",
            REFERENCE_STUB_MODEL,
            "--limit",
            "2",
            "--trials",
            "1",
        ]
    ) == 0

    root = benchmarks / "agentic-fhir-golden-path"
    runnable = load_runnable_manifest(root / "runnable-benchmark.json")
    assert runnable.readiness == "ready"
    assert (root / "package" / "env.json").is_file()
    assert sorted(path.name for path in (root / "package" / "cohort").iterdir()) == [
        "patient-one.fhir.json",
        "patient-two.fhir.json",
    ]
    smoke_evidence = results / runnable.smoke_test.result_bundle_path
    original_evidence = smoke_evidence.read_bytes()
    assert cli.main([
        *common, "eval", "agentic-fhir-golden-path", "--model",
        REFERENCE_STUB_MODEL, "--limit", "2", "--trials", "1",
    ]) == 0
    assert smoke_evidence.read_bytes() == original_evidence
    assert _sha256(smoke_evidence) == runnable.smoke_test.result_bundle_sha256


def test_v2_rejects_unbound_tool_and_nonpublic_governance(tmp_path: Path) -> None:
    spec_path, payload = _fixture(tmp_path / "authoring")
    payload["agentic"]["allowed_tools"] = ["not_a_tool"]  # type: ignore[index]
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="unknown tools"):
        BenchmarkScaffoldSpec.from_json(spec_path)

    spec_path, payload = _fixture(tmp_path / "other-authoring")
    payload["data_governance"]["classification"] = "deidentified"  # type: ignore[index]
    payload["data_governance"]["release_posture"] = "restricted"  # type: ignore[index]
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="initial agentic-fhir adapter"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_v2_tampered_environment_fails_strict_check(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "authoring")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    env_path = receipt.package_path / "env.json"
    environment = json.loads(env_path.read_text(encoding="utf-8"))
    environment["tools"][0]["description"] = "tampered"
    _write_json(env_path, environment)
    _write_json(
        receipt.package_path / "asset-manifest.json",
        PackageAssetManifest.build(receipt.package_path).to_dict(),
    )

    report = check_benchmark(receipt.root)
    assert not report.compatible
    assert any(
        "tool schemas" in issue.message or "env.json" in issue.message
        or "asset-manifest.json" in issue.message
        for issue in report.issues
    ), [issue.message for issue in report.issues]

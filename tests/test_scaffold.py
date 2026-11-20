"""Offline contract tests for deterministic benchmark scaffolding."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from arisekit.package import PackageAssetManifest, load_package
from arisekit.scaffold import (
    BUILD_SPEC_SCHEMA_VERSION,
    BenchmarkScaffoldSpec,
    ScaffoldError,
    ScaffoldLibraryGapError,
    ScaffoldSpecError,
    check_benchmark,
    load_scaffolded_benchmark,
    scaffold_benchmark,
)


ARTIFACT_ROLES = (
    "need-statement",
    "existing-coverage",
    "compliance-scope",
    "data-profile",
    "rubric",
    "study-plan",
    "implementation-plan",
)
MODEL = "provider/model-snapshot"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _rewrite_asset_manifest(package_path: Path) -> None:
    _write_json(
        package_path / "asset-manifest.json",
        PackageAssetManifest.build(package_path).to_dict(),
    )


def _fixture(
    root: Path,
    *,
    source_kind: str = "jsonl",
    scorer: dict[str, object] | None = None,
    readiness_status: str = "ready",
    modality: str = "text",
    attachments: str | None = None,
    classification: str = "synthetic",
    release_posture: str = "public",
) -> tuple[Path, dict[str, object]]:
    root.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, str]] = []
    for role in ARTIFACT_ROLES:
        path = root / f"{role}.md"
        path.write_text(f"# {role}\nreviewed fixture\n", encoding="utf-8")
        artifacts.append(
            {"role": role, "path": path.name, "sha256": _sha256(path)}
        )

    if source_kind == "jsonl":
        source = root / "source.jsonl"
        rows = [
            {
                "case_id": "case-1",
                "vignette": "Choose the correct disposition.",
                "label": "2",
                "service": "emergency-medicine",
                "unused": "not copied to metadata",
            },
            {
                "case_id": "case-2",
                "vignette": "Choose the safest follow-up.",
                "label": "4",
                "service": "primary-care",
                "unused": "not copied to metadata",
            },
        ]
        source.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    else:
        source = root / "source.csv"
        source.write_text(
            "case_id,vignette,label,service,unused\n"
            "case-1,Choose the correct disposition.,2,emergency-medicine,x\n"
            "case-2,Choose the safest follow-up.,4,primary-care,y\n",
            encoding="utf-8",
        )

    prompt = "Return only the numbered choice."
    scorer = scorer or {
        "kind": "choice",
        "primitive": "arisekit.scorer.choice",
        "options": {
            "choices": ["1", "2", "3", "4", "5"],
            "case_sensitive": False,
            "name": "accuracy",
        },
    }
    gaps: list[dict[str, str]] = []
    if scorer["kind"] not in {"exact-match", "contains", "choice", "numeric"}:
        gaps.append(
            {
                "primitive": str(scorer["primitive"]),
                "reason": "benchmark-build-spec.v1 has no deterministic scaffold adapter",
                "owner_or_issue": "unassigned",
            }
        )
    if source_kind not in {"jsonl", "csv"}:
        gaps.append(
            {
                "primitive": f"arisekit.scaffold.source-adapter.{source_kind}",
                "reason": "benchmark-build-spec.v1 has no deterministic source adapter",
                "owner_or_issue": "unassigned",
            }
        )
    if modality != "text":
        gaps.append(
            {
                "primitive": f"arisekit.scaffold.modality-adapter.{modality}",
                "reason": "benchmark-build-spec.v1 has no deterministic modality adapter",
                "owner_or_issue": "unassigned",
            }
        )
    if attachments is not None:
        gaps.append(
            {
                "primitive": f"arisekit.scaffold.attachment-adapter.{attachments}",
                "reason": "benchmark-build-spec.v1 has no deterministic attachment adapter",
                "owner_or_issue": "unassigned",
            }
        )
    payload: dict[str, object] = {
        "schema_version": BUILD_SPEC_SCHEMA_VERSION,
        "benchmark": {
            "name": "ED triage acuity",
            "slug": "ed-triage-acuity",
            "version": "0.1.0",
            "description": "A reviewed deterministic scaffold fixture.",
            "mast_category": "diagnostic",
            "mast_compatible": True,
            "modality": modality,
        },
        "source": {
            "kind": source_kind,
            "path": source.name,
            "sha256": _sha256(source),
            "field_map": {
                "id": "case_id",
                "prompt": "vignette",
                "ground_truth": "label",
                "metadata": {"specialty": "service"},
                "attachments": attachments,
            },
            "system_prompt": {
                "text": prompt,
                "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
        },
        "scorer": scorer,
        "runner": {
            "trials": 3,
            "threads": 4,
            "max_retries": 3,
            "retry_backoff": 1.5,
            "temperature": 0.0,
            "max_tokens": 512,
            "max_cost": 25.0,
            "max_cost_per_call": 0.25,
            "require_known_cost": True,
            "max_calls": 3000,
        },
        "smoke_test": {"model": MODEL, "limit": 10, "trials": 1},
        "first_sweep": [
            {"model": MODEL, "provider": "provider", "trials": 3}
        ],
        "artifacts": artifacts,
        "readiness": {
            "status": readiness_status,
            "data_profile": "materialized",
            "allowed_model_routes": [MODEL],
            "library_gaps": gaps,
            "open_questions": [],
            "user_confirmation": {
                "actor": "fixture clinician",
                "confirmed_at": "2026-07-27T12:00:00Z",
                "text": "Yes, this matches the benchmark I want to build.",
            },
        },
        "data_governance": {
            "classification": classification,
            "release_posture": release_posture,
            "materialization_authorization": {
                "authorized": True,
                "actor": "fixture data steward",
                "confirmed_at": "2026-07-27T12:05:00Z",
                "text": "I authorize materialization for this reviewed benchmark.",
            },
        },
    }
    spec_path = root / "benchmark-build-spec.json"
    _write_json(spec_path, payload)
    return spec_path, payload


@pytest.mark.parametrize("source_kind", ["jsonl", "csv"])
def test_scaffold_round_trip_normalizes_local_sources(
    tmp_path: Path,
    source_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs", source_kind=source_kind)

    def network_is_forbidden(*args, **kwargs):
        raise AssertionError("scaffolding and checking must not resolve a model client")

    monkeypatch.setattr("arisekit.client.resolve_client", network_is_forbidden)
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")

    assert receipt.slug == "ed-triage-acuity"
    assert receipt.item_count == 2
    assert set(path.name for path in receipt.root.iterdir()) == {
        "README.md",
        "build.py",
        "runnable-benchmark.json",
        "package",
    }
    assert receipt.runnable_manifest_sha256 == _sha256(
        receipt.root / "runnable-benchmark.json"
    )
    assert receipt.spec_path == spec_path.resolve()
    assert receipt.spec_sha256 == _sha256(spec_path)
    assert receipt.package_manifest_sha256 == _sha256(
        receipt.package_path / "asset-manifest.json"
    )
    package = load_package(receipt.package_path, verify_assets=True)
    assert [item.id for item in package.items] == ["case-1", "case-2"]
    assert package.items[0].metadata == {"specialty": "emergency-medicine"}
    assert "unused" not in package.items[0].metadata
    assert package.items[0].attachments == []
    assert package.manifest.scorer == {
        "kind": "choice",
        "case_sensitive": False,
        "choices": ["1", "2", "3", "4", "5"],
        "name": "accuracy",
    }
    build_spec_reference = package.manifest.provenance["build_spec"]["path"]
    assert isinstance(build_spec_reference, str)
    assert not Path(build_spec_reference).is_absolute()
    assert (receipt.root / build_spec_reference).resolve() == spec_path.resolve()
    assert package.manifest.provenance["source"]["path"] == payload["source"]["path"]  # type: ignore[index]
    assert package.manifest.provenance["readiness"]["allowed_model_routes"] == [
        MODEL
    ]
    assert not (receipt.root / "benchmark-build-spec.json").exists()
    for artifact in payload["artifacts"]:  # type: ignore[index]
        assert not (receipt.root / Path(artifact["path"]).name).exists()  # type: ignore[index]

    benchmark = load_scaffolded_benchmark(receipt.root)
    assert benchmark.name == "ed-triage-acuity"
    assert benchmark.dataset.system_prompt == "Return only the numbered choice."
    assert benchmark.runner_config.trials == 3
    assert benchmark.runner_config.max_cost == 25.0
    report = check_benchmark(receipt.root)
    assert report.compatible
    assert report.issues == ()
    assert report.item_count == 2
    assert "does not establish clinical quality" in report.claim_boundary
    readme = (receipt.root / "README.md").read_text(encoding="utf-8")
    assert receipt.spec_sha256 in readme
    assert payload["source"]["sha256"] in readme  # type: ignore[index]
    assert (
        "arisekit eval ed-triage-acuity "
        f"--model {MODEL} --limit 10 --trials 1"
    ) in readme
    for artifact in payload["artifacts"]:  # type: ignore[index]
        assert artifact["sha256"] in readme  # type: ignore[index]


def test_builder_plan_reaches_ready_run_results_through_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arisekit import cli
    from arisekit.client import ModelResponse
    from arisekit.runnable import load_manifest

    spec_path, _ = _fixture(tmp_path / "inputs")
    benchmarks_dir = tmp_path / "benchmarks"
    results_dir = tmp_path / "results"

    class EchoClient:
        model = MODEL

        def __call__(self, call):
            return ModelResponse(text=str(call.item.ground_truth), cost=0.0)

    monkeypatch.setattr("arisekit.sut.resolve_client", lambda spec: EchoClient())

    assert cli.main(
        [
            "--benchmarks-dir",
            str(benchmarks_dir),
            "--results-dir",
            str(results_dir),
            "new-benchmark",
            "--spec",
            str(spec_path),
        ]
    ) == 0

    runnable_path = benchmarks_dir / "ed-triage-acuity" / "runnable-benchmark.json"
    initial = load_manifest(runnable_path)
    assert initial.origin == "builder"
    assert initial.readiness == "awaiting_smoke_test"

    assert cli.main(
        [
            "--benchmarks-dir",
            str(benchmarks_dir),
            "--results-dir",
            str(results_dir),
            "eval",
            "ed-triage-acuity",
            "--model",
            MODEL,
            "--limit",
            "10",
            "--trials",
            "1",
        ]
    ) == 0
    ready = load_manifest(runnable_path)
    assert ready.readiness == "ready"
    assert ready.smoke_test.status == "passed"

    assert cli.main(
        [
            "--benchmarks-dir",
            str(benchmarks_dir),
            "--results-dir",
            str(results_dir),
            "eval",
            "ed-triage-acuity",
            "--model",
            MODEL,
        ]
    ) == 0
    reports = list(results_dir.glob("run-results/**/run-results.md"))
    bundles = list(results_dir.glob("run-results/**/run-results.json"))
    assert len(reports) == 2
    assert len(bundles) == 2
    assert "# Run results" in reports[-1].read_text(encoding="utf-8")


def test_checked_in_p0_golden_path_runs_through_cli(tmp_path: Path) -> None:
    from arisekit import cli
    from arisekit.run_inspection import load_and_verify_run_inspection
    from arisekit.runnable import load_manifest

    repository = Path(__file__).resolve().parents[1]
    source = repository / "examples" / "p0-golden-path" / "authoring"
    authoring = tmp_path / "authoring"
    shutil.copytree(source, authoring)

    assert sorted(path.name for path in authoring.glob("*.md")) == [
        "compliance-scope.md",
        "data-profile.md",
        "existing-coverage.md",
        "implementation-plan.md",
        "need-statement.md",
        "rubric.md",
        "study-plan.md",
    ]
    required_headings = {
        "need-statement.md": ("## Problem", "## Defensibility", "## Open questions"),
        "existing-coverage.md": (
            "## Sources queried",
            "## Recommendation",
            "## User decision",
        ),
        "compliance-scope.md": (
            "## Data class considered",
            "## Licensing and redistribution",
            "## Blockers",
        ),
        "data-profile.md": (
            "## Source ledger and draft lineage",
            "## Eval-pattern candidates (hand-off to `arisekit/rubric-design`)",
            "## Fit check against the need statement",
        ),
        "rubric.md": (
            "## Chosen pattern",
            "## ARISEKit library primitive",
            "## NOHARM-style contract",
        ),
        "study-plan.md": (
            "## Panel size",
            "## Conflict-of-interest screening",
            "## Frozen annotation methodology contract",
        ),
        "implementation-plan.md": (
            "## Benchmark identity",
            "## MAST compatibility",
            "## Machine-readable build sidecar",
            "## Data governance for scaffolding",
            "## Dataset loader spec",
            "## Scorer spec",
            "## Runner configuration",
            "## Model list for the first sweep",
            "## Rater tooling handoff",
            "## Library and scaffold-adapter gaps",
            "## Open questions",
            "## Acceptance checklist",
        ),
    }
    for name, headings in required_headings.items():
        document = (authoring / name).read_text(encoding="utf-8")
        assert "_Status:_ accepted" in document
        assert all(heading in document for heading in headings)
    assert len(
        (authoring / "cases.synthetic.jsonl").read_text(encoding="utf-8").splitlines()
    ) == 2

    benchmarks = tmp_path / "benchmarks"
    results = tmp_path / "results"
    common = [
        "--benchmarks-dir",
        str(benchmarks),
        "--results-dir",
        str(results),
    ]
    assert cli.main(
        [
            *common,
            "new-benchmark",
            "--spec",
            str(authoring / "benchmark-build-spec.json"),
        ]
    ) == 0

    runnable_path = benchmarks / "p0-golden-path" / "runnable-benchmark.json"
    assert load_manifest(runnable_path).readiness == "awaiting_smoke_test"
    assert cli.main(
        [
            *common,
            "check-benchmark",
            "p0-golden-path",
            "--verify-linked-provenance",
        ]
    ) == 0
    assert cli.main(
        [
            *common,
            "eval",
            "p0-golden-path",
            "--model",
            "stub/reference",
            "--limit",
            "2",
            "--trials",
            "1",
        ]
    ) == 0

    runnable = load_manifest(runnable_path)
    assert runnable.readiness == "ready"
    assert runnable.smoke_test.status == "passed"
    bundles = list(results.glob("run-results/**/run-results.json"))
    reports = list(results.glob("run-results/**/run-results.md"))
    assert len(bundles) == 1
    assert len(reports) == 1
    verified = load_and_verify_run_inspection(bundles[0], results_root=results)
    assert verified["benchmark"] == "p0-golden-path"
    assert verified["model"] == "stub/reference"
    assert verified["summary"]["completed"] == 2
    assert verified["summary"]["errored"] == 0
    assert "# Run results" in reports[0].read_text(encoding="utf-8")


def test_generated_smoke_command_quotes_reviewed_model_route(
    tmp_path: Path,
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    model = "provider/model; touch unintended"
    payload["smoke_test"]["model"] = model  # type: ignore[index]
    payload["first_sweep"][0]["model"] = model  # type: ignore[index]
    payload["readiness"]["allowed_model_routes"] = [model]  # type: ignore[index]
    _write_json(spec_path, payload)

    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    readme = (receipt.root / "README.md").read_text(encoding="utf-8")

    assert "--model 'provider/model; touch unintended'" in readme
    assert "--model provider/model; touch unintended" not in readme


def test_spec_round_trip_and_relative_path_resolution(tmp_path: Path) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    spec = BenchmarkScaffoldSpec.from_json(spec_path)

    assert spec.to_dict() == payload
    assert spec.source_path == (spec_path.parent / "source.jsonl").resolve()
    restored = BenchmarkScaffoldSpec.from_dict(
        spec.to_dict(), base_dir=spec_path.parent
    )
    assert restored.to_dict() == spec.to_dict()
    assert restored.source_path == spec.source_path


@pytest.mark.parametrize(
    "version",
    [
        "1.0.0-01",
        "1.0.0-alpha..1",
        "1.0.0+build..1",
        "01.0.0",
    ],
)
def test_build_spec_rejects_noncanonical_semver(
    tmp_path: Path,
    version: str,
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    payload["benchmark"]["version"] = version  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="semantic version"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_generated_bytes_and_receipt_digests_are_stable(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    first = scaffold_benchmark(spec_path, output_root=tmp_path / "first")
    second = scaffold_benchmark(spec_path, output_root=tmp_path / "second")

    assert first.spec_sha256 == second.spec_sha256
    assert first.package_manifest_sha256 == second.package_manifest_sha256
    assert first.tree_sha256 == second.tree_sha256
    first_files = {
        path.relative_to(first.root).as_posix(): path.read_bytes()
        for path in first.root.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second.root).as_posix(): path.read_bytes()
        for path in second.root.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert not any("__pycache__" in path for path in first_files)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("malformed", "not valid JSON"),
        ("duplicate", "duplicate item id"),
        ("missing-ground-truth", "missing ground truth"),
    ],
)
def test_bad_source_rows_fail_without_partial_output(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    source = spec_path.parent / "source.jsonl"
    if mutation == "malformed":
        source.write_text('{"case_id":\n', encoding="utf-8")
    elif mutation == "duplicate":
        row = {"case_id": "same", "vignette": "Q", "label": "2", "service": "x"}
        source.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    else:
        row = {"case_id": "case-1", "vignette": "Q", "label": None, "service": "x"}
        source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    payload["source"]["sha256"] = _sha256(source)  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldError, match=message):
        scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    assert not (tmp_path / "benchmarks" / "ed-triage-acuity").exists()


@pytest.mark.parametrize("mutation", ["extra-cell", "missing-trailing-cell"])
def test_csv_rows_must_match_declared_header_width(
    tmp_path: Path,
    mutation: str,
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs", source_kind="csv")
    source = spec_path.parent / "source.csv"
    if mutation == "extra-cell":
        row = "case-1,Prompt,2,service,unused,unexpected\n"
    else:
        row = "case-1,Prompt,2,service\n"
    source.write_text(
        "case_id,vignette,label,service,unused\n" + row,
        encoding="utf-8",
    )
    payload["source"]["sha256"] = _sha256(source)  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldError, match="CSV row width"):
        scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")


def test_hash_mismatches_fail_before_materialization(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    (spec_path.parent / "source.jsonl").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ScaffoldError, match="source SHA-256 mismatch"):
        scaffold_benchmark(spec_path, output_root=tmp_path / "source-out")

    spec_path, _ = _fixture(tmp_path / "other-inputs")
    (spec_path.parent / "rubric.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ScaffoldError, match="artifact 'rubric' SHA-256 mismatch"):
        scaffold_benchmark(spec_path, output_root=tmp_path / "artifact-out")


def test_path_traversal_and_existing_destination_are_refused(tmp_path: Path) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    payload["benchmark"]["slug"] = "../escape"  # type: ignore[index]
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="path separators or traversal"):
        BenchmarkScaffoldSpec.from_json(spec_path)

    spec_path, _ = _fixture(tmp_path / "other-inputs")
    destination = tmp_path / "benchmarks" / "ed-triage-acuity"
    destination.mkdir(parents=True)
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ScaffoldError, match="already exists"):
        scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("target", ["source", "artifact"])
def test_sidecar_paths_reject_parent_traversal_and_symlinks(
    tmp_path: Path,
    target: str,
) -> None:
    spec_path, payload = _fixture(tmp_path / f"{target}-traversal")
    if target == "source":
        payload["source"]["path"] = "../source.jsonl"  # type: ignore[index]
    else:
        payload["artifacts"][0]["path"] = "../need-statement.md"  # type: ignore[index]
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="parent traversal"):
        BenchmarkScaffoldSpec.from_json(spec_path)

    spec_path, payload = _fixture(tmp_path / f"{target}-symlink")
    outside = tmp_path / f"outside-{target}.txt"
    outside.write_text("outside reviewed bytes\n", encoding="utf-8")
    if target == "source":
        linked = spec_path.parent / "source.jsonl"
        linked.unlink()
        os.symlink(outside, linked)
        payload["source"]["sha256"] = _sha256(outside)  # type: ignore[index]
    else:
        linked = spec_path.parent / "need-statement.md"
        linked.unlink()
        os.symlink(outside, linked)
        payload["artifacts"][0]["sha256"] = _sha256(outside)  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldError, match="symlink"):
        scaffold_benchmark(spec_path, output_root=tmp_path / f"{target}-out")


def test_unsupported_scorer_remains_a_blocking_library_gap(tmp_path: Path) -> None:
    scorer = {
        "kind": "rubric-panel",
        "primitive": "arisekit.judges.MultiJudgePanel",
        "options": {},
    }
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        scorer=scorer,
        readiness_status="blocked",
    )
    spec = BenchmarkScaffoldSpec.from_json(spec_path)
    assert spec.readiness.library_gaps[0].primitive == scorer["primitive"]
    with pytest.raises(ScaffoldLibraryGapError, match="refusing partial scaffold"):
        scaffold_benchmark(spec, output_root=tmp_path / "benchmarks")

    payload["readiness"]["status"] = "ready"  # type: ignore[index]
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="no v1 scaffold adapter"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_blocked_spec_preserves_unsupported_modality_and_attachments(
    tmp_path: Path,
) -> None:
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        readiness_status="blocked",
        modality="multimodal",
        attachments="images",
    )
    _write_json(spec_path, payload)

    spec = BenchmarkScaffoldSpec.from_json(spec_path)
    assert spec.benchmark.modality == "multimodal"
    assert spec.source.field_map.attachments == "images"
    assert spec.to_dict() == payload
    with pytest.raises(ScaffoldLibraryGapError, match="refusing partial scaffold"):
        scaffold_benchmark(spec, output_root=tmp_path / "benchmarks")


@pytest.mark.parametrize(
    "unsupported",
    ["scorer", "source", "modality", "attachments"],
)
def test_blocked_unsupported_adapters_require_a_named_gap(
    tmp_path: Path,
    unsupported: str,
) -> None:
    kwargs: dict[str, object] = {"readiness_status": "blocked"}
    if unsupported == "scorer":
        kwargs["scorer"] = {
            "kind": "rubric-panel",
            "primitive": "arisekit.judges.MultiJudgePanel",
            "options": {},
        }
    elif unsupported == "source":
        kwargs["source_kind"] = "warehouse-query"
    elif unsupported == "modality":
        kwargs["modality"] = "multimodal"
    elif unsupported == "attachments":
        kwargs["attachments"] = "images"
    spec_path, payload = _fixture(tmp_path / "inputs", **kwargs)
    payload["readiness"]["library_gaps"] = []  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="must appear exactly"):
        BenchmarkScaffoldSpec.from_json(spec_path)


@pytest.mark.parametrize(
    ("unsupported", "expected_primitive"),
    [
        ("scorer", "arisekit.judges.MultiJudgePanel"),
        (
            "source",
            "arisekit.scaffold.source-adapter.warehouse-query",
        ),
        (
            "modality",
            "arisekit.scaffold.modality-adapter.multimodal",
        ),
        (
            "attachments",
            "arisekit.scaffold.attachment-adapter.images",
        ),
    ],
)
def test_unrelated_gap_cannot_stand_in_for_unsupported_adapter(
    tmp_path: Path,
    unsupported: str,
    expected_primitive: str,
) -> None:
    kwargs: dict[str, object] = {"readiness_status": "blocked"}
    if unsupported == "scorer":
        kwargs["scorer"] = {
            "kind": "rubric-panel",
            "primitive": expected_primitive,
            "options": {},
        }
    elif unsupported == "source":
        kwargs["source_kind"] = "warehouse-query"
    elif unsupported == "modality":
        kwargs["modality"] = "multimodal"
    else:
        kwargs["attachments"] = "images"
    spec_path, payload = _fixture(tmp_path / "inputs", **kwargs)
    payload["readiness"]["library_gaps"] = [  # type: ignore[index]
        {
            "primitive": "arisekit.scaffold.unrelated-adapter",
            "reason": "This unrelated gap remains open.",
            "owner_or_issue": "unassigned",
        }
    ]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError) as exc_info:
        BenchmarkScaffoldSpec.from_json(spec_path)

    assert expected_primitive in str(exc_info.value)


def test_blocked_sidecar_requires_a_recorded_blocking_condition(
    tmp_path: Path,
) -> None:
    spec_path, _ = _fixture(
        tmp_path / "inputs",
        readiness_status="blocked",
    )

    with pytest.raises(ScaffoldSpecError, match="no blocking condition"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_provisional_data_is_an_explicit_non_adapter_blocker(tmp_path: Path) -> None:
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        readiness_status="blocked",
    )
    payload["readiness"]["data_profile"] = "provisional"  # type: ignore[index]
    _write_json(spec_path, payload)

    spec = BenchmarkScaffoldSpec.from_json(spec_path)

    assert spec.readiness.status == "blocked"
    assert spec.readiness.data_profile == "provisional"
    assert spec.readiness.library_gaps == ()


def test_ready_spec_enforces_modality_attachment_and_model_route_gates(
    tmp_path: Path,
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    payload["source"]["field_map"]["attachments"] = "images"  # type: ignore[index]
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="attachments must be null"):
        BenchmarkScaffoldSpec.from_json(spec_path)

    spec_path, _ = _fixture(tmp_path / "modality-inputs", modality="multimodal")
    with pytest.raises(ScaffoldSpecError, match="modality .*no build-spec v1 adapter"):
        BenchmarkScaffoldSpec.from_json(spec_path)

    spec_path, payload = _fixture(tmp_path / "other-inputs")
    payload["first_sweep"].append(  # type: ignore[union-attr]
        {"model": "other/disallowed", "provider": "other", "trials": 3}
    )
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="first-sweep models"):
        BenchmarkScaffoldSpec.from_json(spec_path)

    spec_path, payload = _fixture(tmp_path / "missing-provider-inputs")
    payload["readiness"]["allowed_model_routes"].append("other/model")  # type: ignore[index]
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="missing from first_sweep"):
        BenchmarkScaffoldSpec.from_json(spec_path)


@pytest.mark.parametrize(
    "field_path",
    [
        ("readiness", "user_confirmation", "confirmed_at"),
        (
            "data_governance",
            "materialization_authorization",
            "confirmed_at",
        ),
    ],
)
def test_ready_spec_requires_rfc3339_confirmation_timestamps(
    tmp_path: Path,
    field_path: tuple[str, str, str],
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    first, second, third = field_path
    payload[first][second][third] = "2026-07-27 12:00"  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="RFC 3339"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_runner_requires_at_least_one_retry_attempt(tmp_path: Path) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    payload["runner"]["max_retries"] = 0  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="max_retries must be a positive integer"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_runner_rejects_per_call_budget_above_total_budget(tmp_path: Path) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    payload["runner"]["max_cost"] = 1.0  # type: ignore[index]
    payload["runner"]["max_cost_per_call"] = 1.01  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="cannot exceed runner.max_cost"):
        BenchmarkScaffoldSpec.from_json(spec_path)


@pytest.mark.parametrize(
    "field",
    ["smoke-model", "sweep-model", "sweep-provider", "allowed-route"],
)
def test_model_routes_and_providers_reject_control_characters(
    tmp_path: Path,
    field: str,
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    if field == "smoke-model":
        payload["smoke_test"]["model"] = f"{MODEL}\nsecond-command"  # type: ignore[index]
    elif field == "sweep-model":
        payload["first_sweep"][0]["model"] = f"{MODEL}\nsecond-command"  # type: ignore[index]
    elif field == "sweep-provider":
        payload["first_sweep"][0]["provider"] = "provider\nsecond-command"  # type: ignore[index]
    else:
        payload["readiness"]["allowed_model_routes"][0] = f"{MODEL}\nsecond-command"  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="control characters"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_checker_detects_package_and_provenance_tampering(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    cases = receipt.package_path / "cases.jsonl"
    cases.write_text(cases.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    report = check_benchmark(receipt.root)
    assert not report.compatible
    assert any(issue.code == "package-integrity" for issue in report.issues)

    spec_path, _ = _fixture(tmp_path / "other-inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "other-benchmarks")
    (spec_path.parent / "study-plan.md").write_text("stale\n", encoding="utf-8")
    report = check_benchmark(receipt.root)
    assert report.compatible
    report = check_benchmark(receipt.root, verify_linked_provenance=True)
    assert not report.compatible
    assert any(
        issue.code == "stale-provenance" and "study-plan" in issue.message
        for issue in report.issues
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", 123),
        ("version", 1),
        ("provenance", [["runner", {}]]),
    ],
)
def test_checker_rejects_raw_manifest_type_coercion(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    manifest_path = receipt.package_path / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    _write_json(manifest_path, manifest)
    _rewrite_asset_manifest(receipt.package_path)

    report = check_benchmark(receipt.root)

    assert not report.compatible
    assert any(issue.code == "invalid-manifest" for issue in report.issues)
    with pytest.raises(ScaffoldError, match="manifest"):
        load_scaffolded_benchmark(receipt.root)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 123),
        ("metadata", [["specialty", "emergency-medicine"]]),
        ("attachments", ""),
    ],
)
def test_checker_rejects_raw_case_type_coercion(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    cases_path = receipt.package_path / "cases.jsonl"
    rows = [
        json.loads(line)
        for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows[0][field] = value
    cases_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    _rewrite_asset_manifest(receipt.package_path)

    report = check_benchmark(receipt.root)

    assert not report.compatible
    assert any(issue.code == "invalid-items" for issue in report.issues)
    with pytest.raises(ScaffoldError, match="cases|id|metadata|attachments"):
        load_scaffolded_benchmark(receipt.root)


def test_nonpublic_scaffold_adds_data_controls_and_digested_authorization(
    tmp_path: Path,
) -> None:
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        classification="deidentified",
        release_posture="private",
    )
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")

    assert (receipt.root / ".gitignore").read_text(encoding="utf-8") == (
        "package/cases.jsonl\n"
    )
    readme = (receipt.root / "README.md").read_text(encoding="utf-8")
    assert "must not be committed without a new, explicit release decision" in readme
    assert receipt.package_manifest_sha256 in readme
    assert f"`{MODEL}` -> `provider`" in readme
    assert "--provider-authorization provider-disclosure.json" in readme
    assert "`judge_providers`: `[]`" in readme
    manifest_text = (receipt.package_path / "benchmark.json").read_text(
        encoding="utf-8"
    )
    authorization = payload["data_governance"]["materialization_authorization"]  # type: ignore[index]
    assert authorization["text"] not in manifest_text  # type: ignore[index]
    assert hashlib.sha256(authorization["text"].encode("utf-8")).hexdigest() in manifest_text  # type: ignore[index]
    assert check_benchmark(receipt.root).compatible

    (receipt.root / ".gitignore").write_text(
        "package/cases.jsonl\n!package/cases.jsonl\n",
        encoding="utf-8",
    )
    bypass_report = check_benchmark(receipt.root)
    assert not bypass_report.compatible
    assert any(
        issue.code == "invalid-data-control" for issue in bypass_report.issues
    )


@pytest.mark.parametrize(
    ("classification", "release_posture", "authorized", "message"),
    [
        ("limited", "restricted", True, "cannot be materialized"),
        ("identifiable", "private", True, "cannot be materialized"),
        ("deidentified", "public", True, "public release posture"),
        ("synthetic", "public", False, "authorization is false"),
    ],
)
def test_ready_spec_enforces_data_governance_gates(
    tmp_path: Path,
    classification: str,
    release_posture: str,
    authorized: bool,
    message: str,
) -> None:
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        classification=classification,
        release_posture=release_posture,
    )
    payload["data_governance"]["materialization_authorization"]["authorized"] = authorized  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match=message):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_blocked_refusal_preserves_complete_audit_record(tmp_path: Path) -> None:
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        readiness_status="blocked",
    )
    refusal = payload["data_governance"]["materialization_authorization"]  # type: ignore[index]
    refusal.update(  # type: ignore[union-attr]
        {
            "authorized": False,
            "actor": "fixture data steward",
            "confirmed_at": "2026-07-27T13:10:11-04:00",
            "text": "No. Do not materialize normalized case rows.",
        }
    )
    _write_json(spec_path, payload)

    spec = BenchmarkScaffoldSpec.from_json(spec_path)

    authorization = spec.data_governance.materialization_authorization
    assert not authorization.authorized
    assert authorization.actor == refusal["actor"]  # type: ignore[index]
    assert authorization.confirmed_at == refusal["confirmed_at"]  # type: ignore[index]
    assert authorization.text == refusal["text"]  # type: ignore[index]


@pytest.mark.parametrize("missing_field", ["actor", "confirmed_at", "text"])
def test_blocked_refusal_rejects_incomplete_audit_record(
    tmp_path: Path,
    missing_field: str,
) -> None:
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        readiness_status="blocked",
    )
    authorization = payload["data_governance"]["materialization_authorization"]  # type: ignore[index]
    authorization["authorized"] = False  # type: ignore[index]
    authorization[missing_field] = None  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="refusal must include"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_blocked_refusal_requires_rfc3339_timestamp(tmp_path: Path) -> None:
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        readiness_status="blocked",
    )
    authorization = payload["data_governance"]["materialization_authorization"]  # type: ignore[index]
    authorization["authorized"] = False  # type: ignore[index]
    authorization["confirmed_at"] = "2026-07-27 13:10"  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldSpecError, match="RFC 3339 for a refusal"):
        BenchmarkScaffoldSpec.from_json(spec_path)


def test_copied_scaffold_has_no_runtime_dependency_on_authoring_files(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    spec_path, _ = _fixture(inputs)
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    copied = tmp_path / "portable" / "nested" / receipt.slug
    copied.parent.mkdir(parents=True)
    shutil.copytree(receipt.root, copied)
    shutil.rmtree(inputs)

    report = check_benchmark(copied)
    assert report.compatible
    benchmark = load_scaffolded_benchmark(copied)
    assert benchmark.name == receipt.slug
    assert len(benchmark.dataset) == receipt.item_count
    linked_report = check_benchmark(copied, verify_linked_provenance=True)
    assert not linked_report.compatible
    assert any(issue.code == "stale-provenance" for issue in linked_report.issues)


def test_checker_and_safe_loader_never_execute_generated_build(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    marker = tmp_path / "executed.txt"
    malicious = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "raise RuntimeError('generated build.py must remain inert')\n"
    )
    (receipt.root / "build.py").write_text(malicious, encoding="utf-8")
    manifest_path = receipt.package_path / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"]["generated_build_sha256"] = hashlib.sha256(
        malicious.encode("utf-8")
    ).hexdigest()
    _write_json(manifest_path, manifest)
    _rewrite_asset_manifest(receipt.package_path)

    report = check_benchmark(receipt.root)
    assert not report.compatible
    assert any(issue.code == "safe-load-failed" for issue in report.issues)
    with pytest.raises(ScaffoldError, match="runnable benchmark contract"):
        load_scaffolded_benchmark(receipt.root)
    assert not marker.exists()


def test_verify_linked_rejects_joint_manifest_and_asset_manifest_tamper(
    tmp_path: Path,
) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    manifest_path = receipt.package_path / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"]["first_sweep"][0]["trials"] = 99
    _write_json(manifest_path, manifest)
    _rewrite_asset_manifest(receipt.package_path)

    default_report = check_benchmark(receipt.root)
    assert not default_report.compatible
    assert any(
        issue.code == "invalid-runnable-manifest"
        for issue in default_report.issues
    )
    report = check_benchmark(receipt.root, verify_linked_provenance=True)
    assert not report.compatible
    assert any(issue.code == "manifest-mismatch" for issue in report.issues)


def test_default_checker_rejects_mast_incompatible_package(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    manifest_path = receipt.package_path / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mast_compatible"] = False
    _write_json(manifest_path, manifest)
    _rewrite_asset_manifest(receipt.package_path)

    report = check_benchmark(receipt.root)
    assert not report.compatible
    assert any(issue.code == "mast-incompatible" for issue in report.issues)


def test_checker_rejects_incomplete_route_to_provider_map(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    manifest_path = receipt.package_path / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"]["readiness"]["allowed_model_routes"].append(
        "other/model"
    )
    _write_json(manifest_path, manifest)
    _rewrite_asset_manifest(receipt.package_path)

    report = check_benchmark(receipt.root)

    assert not report.compatible
    assert any(
        issue.code == "invalid-provenance"
        and "missing from first_sweep" in issue.message
        for issue in report.issues
    )


def test_default_checker_rejects_malformed_portable_provenance(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    manifest_path = receipt.package_path / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"]["unexpected"] = {"looks": "plausible"}
    del manifest["provenance"]["smoke_test"]
    _write_json(manifest_path, manifest)
    _rewrite_asset_manifest(receipt.package_path)

    report = check_benchmark(receipt.root)
    assert not report.compatible
    assert any(issue.code == "invalid-provenance" for issue in report.issues)


def test_checker_enforces_exact_regular_root_topology(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path / "extra-inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "extra-benchmarks")
    (receipt.root / "run-me.py").write_text("raise RuntimeError\n", encoding="utf-8")
    extra_report = check_benchmark(receipt.root)
    assert not extra_report.compatible
    assert any(
        issue.code == "invalid-root-topology" for issue in extra_report.issues
    )

    spec_path, _ = _fixture(tmp_path / "symlink-inputs")
    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "symlink-benchmarks")
    outside_readme = tmp_path / "outside-readme.md"
    outside_readme.write_text("external\n", encoding="utf-8")
    (receipt.root / "README.md").unlink()
    os.symlink(outside_readme, receipt.root / "README.md")
    symlink_report = check_benchmark(receipt.root)
    assert not symlink_report.compatible
    assert any(
        issue.code == "invalid-root-topology" for issue in symlink_report.issues
    )


def test_unsupported_source_kind_remains_a_blocking_library_gap(
    tmp_path: Path,
) -> None:
    spec_path, payload = _fixture(
        tmp_path / "inputs",
        source_kind="warehouse-query",
        readiness_status="blocked",
    )
    spec = BenchmarkScaffoldSpec.from_json(spec_path)
    assert spec.source.kind == "warehouse-query"
    with pytest.raises(ScaffoldLibraryGapError, match="refusing partial scaffold"):
        scaffold_benchmark(spec, output_root=tmp_path / "benchmarks")

    payload["readiness"]["status"] = "ready"  # type: ignore[index]
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="source kind .*no build-spec v1 adapter"):
        BenchmarkScaffoldSpec.from_json(spec_path)


@pytest.mark.parametrize(
    ("scorer", "ground_truth", "message"),
    [
        (
            {
                "kind": "numeric",
                "primitive": "arisekit.scorer.numeric",
                "options": {"atol": 0.1},
            },
            "not-a-number",
            "must be numeric",
        ),
        (
            {
                "kind": "choice",
                "primitive": "arisekit.scorer.choice",
                "options": {"choices": ["1", "2"]},
            },
            "3",
            "not in scorer choices",
        ),
        (
            {
                "kind": "contains",
                "primitive": "arisekit.scorer.contains",
                "options": {},
            },
            "",
            "non-empty strings",
        ),
    ],
)
def test_scorer_aware_ground_truth_validation(
    tmp_path: Path,
    scorer: dict[str, object],
    ground_truth: object,
    message: str,
) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs", scorer=scorer)
    source_path = spec_path.parent / "source.jsonl"
    row = {
        "case_id": "case-1",
        "vignette": "A text-only prompt",
        "label": ground_truth,
        "service": "test",
    }
    source_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    payload["source"]["sha256"] = _sha256(source_path)  # type: ignore[index]
    _write_json(spec_path, payload)

    with pytest.raises(ScaffoldError, match=message):
        scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")


def test_null_system_prompt_is_preserved(tmp_path: Path) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    payload["source"]["system_prompt"] = None  # type: ignore[index]
    _write_json(spec_path, payload)

    receipt = scaffold_benchmark(spec_path, output_root=tmp_path / "benchmarks")
    assert load_scaffolded_benchmark(receipt.root).dataset.system_prompt is None


def test_duplicate_json_keys_and_unknown_spec_fields_fail_strictly(tmp_path: Path) -> None:
    spec_path, payload = _fixture(tmp_path / "inputs")
    spec_path.write_text('{"schema_version":"x","schema_version":"y"}\n', encoding="utf-8")
    with pytest.raises(ScaffoldSpecError, match="duplicate JSON key"):
        BenchmarkScaffoldSpec.from_json(spec_path)

    spec_path, payload = _fixture(tmp_path / "other-inputs")
    payload["unexpected"] = True
    _write_json(spec_path, payload)
    with pytest.raises(ScaffoldSpecError, match="unknown=.*unexpected"):
        BenchmarkScaffoldSpec.from_json(spec_path)

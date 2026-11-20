"""CLI wiring for deterministic benchmark scaffolding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import arisekit.cli as cli
import arisekit.env as env
import arisekit.package as package
import arisekit.scaffold as scaffold
import arisekit.sut as sut
from arisekit.egress import ProviderDisclosureAuthorization
from arisekit.types import BenchmarkItem


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authorization() -> ProviderDisclosureAuthorization:
    return ProviderDisclosureAuthorization(
        generated_bundle_hash=_hash("bundle"),
        access_classification="private",
        solver_providers=("provider-a",),
        judge_providers=(),
        authorization_artifact_hash=_hash("approval"),
        approved_by="data-owner",
        approved_at="2026-07-27T10:30:00-04:00",
    )


def test_new_benchmark_parser_requires_a_spec() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["new-benchmark", "--spec", "build.json"])

    assert args.func is cli.cmd_new_benchmark
    assert args.spec == "build.json"


def test_jobs_parser_exposes_submit_status_and_resume() -> None:
    parser = cli.build_parser()
    submit = parser.parse_args(["jobs", "submit", "job.json"])
    status = parser.parse_args(["jobs", "status", "job-1"])
    resume = parser.parse_args(["jobs", "resume", "job-1"])

    assert submit.func is cli.cmd_jobs_submit
    assert status.func is cli.cmd_jobs_status
    assert resume.func is cli.cmd_jobs_resume


def test_jobs_cli_submits_inspects_and_resumes_item_emission(
    tmp_path: Path,
    capsys,
) -> None:
    from arisekit.runtime.execution import ExecutionJob, ExecutionTask, JobKind

    job = ExecutionJob(
        job_id="cli-emission",
        kind=JobKind.ITEM_EMISSION,
        tasks=(
            ExecutionTask(
                id="case-1",
                payload={
                    "item": {"id": "case-1", "prompt": "Prompt"},
                    "output_path": "artifacts/items.jsonl",
                },
            ),
        ),
        input_artifacts={"shape-spec": "a" * 64},
    )
    spec_path = tmp_path / "execution-job.json"
    spec_path.write_text(json.dumps(job.to_dict()) + "\n", encoding="utf-8")
    jobs_dir = tmp_path / "jobs"
    prefix = ["--jobs-dir", str(jobs_dir), "jobs"]

    assert cli.main([*prefix, "submit", str(spec_path)]) == 0
    submit_output = capsys.readouterr().out
    assert "succeeded=1 failed=0 resumed=0" in submit_output
    assert (jobs_dir / job.job_id / "artifacts" / "items.jsonl").is_file()

    assert cli.main([*prefix, "status", job.job_id]) == 0
    assert "status: complete" in capsys.readouterr().out

    assert cli.main([*prefix, "resume", job.job_id]) == 0
    assert "succeeded=1 failed=0 resumed=1" in capsys.readouterr().out


def test_scaffold_alias_uses_new_benchmark_command() -> None:
    args = cli.build_parser().parse_args(["scaffold", "--spec", "build.json"])

    assert args.func is cli.cmd_new_benchmark


def test_check_benchmark_parser_accepts_provenance_verification() -> None:
    args = cli.build_parser().parse_args(
        ["check-benchmark", "demo", "--verify-linked-provenance"]
    )

    assert args.func is cli.cmd_check_benchmark
    assert args.target == "demo"
    assert args.verify_linked_provenance is True


def test_eval_preserves_benchmark_runner_defaults_without_overrides() -> None:
    args = cli.build_parser().parse_args(
        ["eval", "demo", "--model", "provider/model"]
    )

    assert args.trials is None
    assert args.threads is None


def test_provider_authorization_flag_is_available_on_every_run_command() -> None:
    parser = cli.build_parser()
    cases = (
        ["eval", "demo", "--model", "provider/model"],
        ["run-package", "package", "--model", "provider/model"],
        ["run-tool", "package", "--model", "provider/model"],
    )

    for command in cases:
        args = parser.parse_args(
            [*command, "--provider-authorization", "approval.json"]
        )
        assert args.provider_authorization == "approval.json"


def test_eval_loads_strict_provider_authorization_and_passes_object(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected = _authorization()
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(
        json.dumps(expected.to_dict()),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class _Benchmark:
        def run(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                benchmark="fixture",
                model="provider/model",
                summary=SimpleNamespace(
                    completed=1,
                    errored=0,
                    skipped=0,
                    cost_total=0.0,
                    output_path=tmp_path / "raw.jsonl",
                    manifest_digest=None,
                ),
                metrics=[],
            )

    monkeypatch.setattr(cli, "_load_benchmark", lambda name, root: _Benchmark())

    code = cli.main(
        [
            "--benchmarks-dir",
            str(tmp_path),
            "--results-dir",
            str(tmp_path),
            "eval",
            "fixture",
            "--model",
            "provider/model",
            "--provider-authorization",
            str(authorization_path),
        ]
    )

    assert code == 0
    assert captured["provider_authorization"] == expected


def test_eval_rejects_duplicate_authorization_keys_before_loading_benchmark(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(
        '{"schema_version":"one","schema_version":"two"}',
        encoding="utf-8",
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("invalid authorization must fail before benchmark load")

    monkeypatch.setattr(cli, "_load_benchmark", unexpected)

    code = cli.main(
        [
            "--benchmarks-dir",
            str(tmp_path),
            "eval",
            "fixture",
            "--model",
            "provider/model",
            "--provider-authorization",
            str(authorization_path),
        ]
    )

    assert code == 2
    assert "duplicate JSON key 'schema_version'" in capsys.readouterr().out


def test_check_benchmark_reports_a_missing_target(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = cli.main(
        [
            "--benchmarks-dir",
            str(tmp_path),
            "check-benchmark",
            "missing",
        ]
    )

    assert exit_code == 2
    assert "not structurally compatible" in capsys.readouterr().out


def test_new_benchmark_reports_an_invalid_spec(
    tmp_path: Path,
    capsys,
) -> None:
    spec = tmp_path / "invalid.json"
    spec.write_text("{}\n", encoding="utf-8")

    exit_code = cli.main(
        [
            "--benchmarks-dir",
            str(tmp_path / "benchmarks"),
            "new-benchmark",
            "--spec",
            str(spec),
        ]
    )

    assert exit_code == 2
    assert "cannot scaffold benchmark" in capsys.readouterr().out


def test_new_benchmark_prints_quoted_commands_with_custom_roots(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    spec = SimpleNamespace(
        data_governance=SimpleNamespace(release_posture="private"),
        smoke_test=SimpleNamespace(
            model="provider/model with space",
            limit=4,
            trials=2,
        )
    )
    receipt = SimpleNamespace(
        root=tmp_path / "benchmark root" / "demo",
        item_count=3,
        spec_sha256="a" * 64,
        package_manifest_sha256="b" * 64,
        tree_sha256="c" * 64,
        slug="demo",
    )
    monkeypatch.setattr(
        scaffold.BenchmarkScaffoldSpec,
        "from_json",
        classmethod(lambda cls, path: spec),
    )
    monkeypatch.setattr(
        scaffold,
        "scaffold_benchmark",
        lambda loaded, output_root: receipt,
    )

    code = cli.main(
        [
            "--benchmarks-dir",
            str(tmp_path / "benchmark root"),
            "--results-dir",
            str(tmp_path / "result root"),
            "new-benchmark",
            "--spec",
            "build spec.json",
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert f"--benchmarks-dir '{tmp_path / 'benchmark root'}'" in output
    assert f"--results-dir '{tmp_path / 'result root'}'" in output
    assert "check-benchmark demo --verify-linked-provenance" in output
    assert "--model 'provider/model with space'" in output
    assert "--provider-authorization provider-disclosure.json" in output


def test_run_tool_rebuilds_through_package_policy(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    cohort = tmp_path / "case.fhir.json"
    cohort.write_text("{}\n", encoding="utf-8")
    loaded_package = SimpleNamespace(
        cohort=[cohort],
        manifest=SimpleNamespace(provenance={}),
    )
    calls: list[object] = []
    run_kwargs: dict[str, object] = {}
    authorization = _authorization()
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(
        json.dumps(authorization.to_dict()),
        encoding="utf-8",
    )

    class _Benchmark:
        def run(self, *args, **kwargs):
            run_kwargs.update(kwargs)
            raise ValueError("model route is not in reviewed allowlist")

    def from_package(pkg, *, scorer):
        calls.extend([pkg, scorer])
        return _Benchmark()

    monkeypatch.setattr(
        package,
        "load_package",
        lambda path, *, verify_assets=False: loaded_package,
    )
    monkeypatch.setattr(env, "FHIREnvironment", lambda bundles: object())
    monkeypatch.setattr(env, "fhir_tools", lambda environment: [])
    monkeypatch.setattr(sut.SystemUnderTest, "from_agent", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli.Benchmark, "from_package", from_package)

    code = cli.main(
        [
            "run-tool",
            str(tmp_path / "package"),
            "--model",
            "provider/not-reviewed",
            "--provider-authorization",
            str(authorization_path),
        ]
    )

    assert code == 2
    assert calls[0] is loaded_package
    assert run_kwargs["provider_authorization"] == authorization
    assert "not in reviewed allowlist" in capsys.readouterr().out


def test_run_tool_v2_uses_strict_package_binding_and_model_route(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    loaded_package = SimpleNamespace(
        cohort=[tmp_path / "case.fhir.json"],
        manifest=SimpleNamespace(
            provenance={
                "build_spec": {
                    "schema_version": "arisekit.benchmark-build-spec.v2"
                }
            }
        ),
    )
    constructed: list[object] = []
    run_kwargs: dict[str, object] = {}

    class _Benchmark:
        def run(self, **kwargs):
            run_kwargs.update(kwargs)
            return SimpleNamespace(
                benchmark="agentic-fixture",
                model="provider/model",
                summary=SimpleNamespace(
                    completed=1,
                    errored=0,
                    skipped=0,
                    cost_total=0.0,
                ),
                metrics=[],
            )

    def from_package(pkg):
        constructed.append(pkg)
        return _Benchmark()

    monkeypatch.setattr(cli, "_load_runtime_package", lambda path: loaded_package)
    monkeypatch.setattr(cli.Benchmark, "from_package", from_package)
    monkeypatch.setattr(
        env,
        "FHIREnvironment",
        lambda bundles: (_ for _ in ()).throw(
            AssertionError("v2 CLI must not build a shared FHIR environment")
        ),
    )

    code = cli.main(
        [
            "--results-dir",
            str(tmp_path / "results"),
            "run-tool",
            str(tmp_path / "package"),
            "--model",
            "provider/model",
            "--trials",
            "2",
        ]
    )

    assert code == 0
    assert constructed == [loaded_package]
    assert run_kwargs["model"] == "provider/model"
    assert run_kwargs["trials"] == 2
    assert run_kwargs["results_dir"] == tmp_path / "results"
    assert "completed=1 errored=0 skipped=0" in capsys.readouterr().out


def test_run_tool_v2_rejects_legacy_execution_overrides(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    loaded_package = SimpleNamespace(
        cohort=[tmp_path / "case.fhir.json"],
        manifest=SimpleNamespace(
            provenance={
                "build_spec": {
                    "schema_version": "arisekit.benchmark-build-spec.v2"
                }
            }
        ),
    )
    monkeypatch.setattr(cli, "_load_runtime_package", lambda path: loaded_package)

    code = cli.main(
        [
            "run-tool",
            str(tmp_path / "package"),
            "--model",
            "provider/model",
            "--max-iters",
            "12",
        ]
    )

    assert code == 2
    assert "binds the system prompt and max turns" in capsys.readouterr().out


def test_run_package_strictly_loads_assets_and_passes_authorization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authorization = _authorization()
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(
        json.dumps(authorization.to_dict()),
        encoding="utf-8",
    )
    package_path = tmp_path / "package"
    package_path.mkdir()
    (package_path / "asset-manifest.json").write_text("{}\n", encoding="utf-8")
    loaded_package = SimpleNamespace(
        manifest=SimpleNamespace(provenance={}),
    )
    load_calls: list[tuple[object, bool]] = []
    run_kwargs: dict[str, object] = {}

    class _Benchmark:
        def run(self, **kwargs):
            run_kwargs.update(kwargs)
            return SimpleNamespace(
                benchmark="fixture",
                model="provider/model",
                summary=SimpleNamespace(
                    completed=1,
                    errored=0,
                    skipped=0,
                    cost_total=0.0,
                    output_path=tmp_path / "raw.jsonl",
                    manifest_digest=None,
                ),
                metrics=[],
            )

    def load_package(path, *, verify_assets=False):
        load_calls.append((path, verify_assets))
        return loaded_package

    monkeypatch.setattr(package, "load_package", load_package)
    monkeypatch.setattr(
        cli.Benchmark,
        "from_package",
        lambda pkg: _Benchmark(),
    )

    code = cli.main(
        [
            "--results-dir",
            str(tmp_path),
            "run-package",
            str(package_path),
            "--model",
            "provider/model",
            "--provider-authorization",
            str(authorization_path),
        ]
    )

    assert code == 0
    assert load_calls == [(str(package_path), True)]
    assert run_kwargs["provider_authorization"] == authorization


def test_runtime_package_loading_preserves_legacy_packages_without_inventory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_path = tmp_path / "legacy"
    package_path.mkdir()
    (package_path / "benchmark.json").write_text(
        json.dumps(
            {
                "id": "legacy",
                "name": "Legacy",
                "provenance": {},
            }
        ),
        encoding="utf-8",
    )
    loaded_package = SimpleNamespace(
        manifest=SimpleNamespace(provenance={}),
    )
    load_calls: list[tuple[object, bool]] = []

    def load_package(path, *, verify_assets=False):
        load_calls.append((path, verify_assets))
        return loaded_package

    monkeypatch.setattr(package, "load_package", load_package)

    assert cli._load_runtime_package(package_path) is loaded_package
    assert load_calls == [(package_path, False)]


def test_runtime_package_loading_rejects_non_json_manifest_constants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_path = tmp_path / "non-json-manifest"
    package_path.mkdir()
    (package_path / "benchmark.json").write_text(
        '{"id":"fixture","name":"Fixture","provenance":{"value":NaN}}\n',
        encoding="utf-8",
    )
    loaded = False

    def unexpected_load(path, *, verify_assets=False):
        nonlocal loaded
        loaded = True
        return object()

    monkeypatch.setattr(package, "load_package", unexpected_load)

    try:
        cli._load_runtime_package(package_path)
    except ValueError as exc:
        assert "non-finite JSON number NaN" in str(exc)
    else:
        raise AssertionError("non-JSON manifest constants must be rejected")
    assert loaded is False


def test_runtime_package_loading_requires_inventory_for_generated_or_nonpublic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    policies = (
        {
            "build_spec": {
                "schema_version": "arisekit.benchmark-build-spec.v1"
            }
        },
        {
            "data_governance": {
                "classification": "public",
                "release_posture": "held-out",
            }
        },
        {
            "data_governance": {
                "classification": "identifiable",
                "release_posture": "public",
            }
        },
    )
    load_calls: list[tuple[object, bool]] = []

    def load_package(path, *, verify_assets=False):
        load_calls.append((path, verify_assets))
        raise ValueError("strict verification requires asset-manifest.json")

    monkeypatch.setattr(package, "load_package", load_package)

    for index, provenance in enumerate(policies):
        package_path = tmp_path / f"package-{index}"
        package_path.mkdir()
        (package_path / "benchmark.json").write_text(
            json.dumps(
                {
                    "id": f"package-{index}",
                    "name": "Policy package",
                    "provenance": provenance,
                }
            ),
            encoding="utf-8",
        )
        try:
            cli._load_runtime_package(package_path)
        except ValueError as exc:
            assert "strict verification requires" in str(exc)
        else:
            raise AssertionError("policy package must require strict assets")

    assert load_calls == [
        (tmp_path / "package-0", True),
        (tmp_path / "package-1", True),
        (tmp_path / "package-2", True),
    ]


def test_run_package_rejects_tampered_inventory_before_benchmark_construction(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    package_path = package.write_package(
        tmp_path / "strict-package",
        manifest=package.BenchmarkManifest(
            id="strict-package",
            name="Strict package",
            scorer={"kind": "exact-match"},
        ),
        items=[BenchmarkItem(id="case-1", prompt="Prompt", ground_truth="Answer")],
        write_asset_manifest=True,
    )
    with (package_path / "cases.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("{}\n")
    constructed = False

    def unexpected_from_package(pkg):
        nonlocal constructed
        constructed = True
        raise AssertionError("tampered package must not reach benchmark construction")

    monkeypatch.setattr(cli.Benchmark, "from_package", unexpected_from_package)

    code = cli.main(
        [
            "run-package",
            str(package_path),
            "--model",
            "provider/model",
        ]
    )

    assert code == 2
    assert constructed is False
    assert "asset size mismatch for cases.jsonl" in capsys.readouterr().out


def test_run_tool_rejects_tampered_cohort_before_environment_initialization(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    package_path = package.write_package(
        tmp_path / "agentic-package",
        manifest=package.BenchmarkManifest(
            id="agentic-package",
            name="Agentic package",
            modality="agentic-fhir",
            scorer={"kind": "pass-at-one"},
        ),
        items=[BenchmarkItem(id="case-1", prompt="Find the patient")],
        cohort_bundles=[{"resourceType": "Bundle", "id": "cohort-1"}],
        write_asset_manifest=True,
    )
    cohort_path = next((package_path / "cohort").glob("*.fhir.json"))
    cohort_path.write_text(
        '{"resourceType":"Bundle","id":"changed"}\n',
        encoding="utf-8",
    )
    initialized = False

    def unexpected_environment(bundles):
        nonlocal initialized
        initialized = True
        raise AssertionError("unverified cohort must not initialize an environment")

    monkeypatch.setattr(env, "FHIREnvironment", unexpected_environment)

    code = cli.main(
        [
            "run-tool",
            str(package_path),
            "--model",
            "provider/model",
        ]
    )

    assert code == 2
    assert initialized is False
    assert "asset size mismatch for cohort/" in capsys.readouterr().out


def test_generated_package_without_inventory_fails_before_invalid_cohort_parse(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    package_path = package.write_package(
        tmp_path / "generated-package",
        manifest=package.BenchmarkManifest(
            id="generated-package",
            name="Generated package",
            modality="agentic-fhir",
            scorer={"kind": "pass-at-one"},
            provenance={
                "build_spec": {
                    "schema_version": "arisekit.benchmark-build-spec.v1"
                }
            },
        ),
        items=[BenchmarkItem(id="case-1", prompt="Find the patient")],
        cohort_bundles=[{"resourceType": "Bundle", "id": "cohort-1"}],
    )
    cohort_path = next((package_path / "cohort").glob("*.fhir.json"))
    cohort_path.write_text("{not-json}\n", encoding="utf-8")
    initialized = False

    def unexpected_environment(bundles):
        nonlocal initialized
        initialized = True
        return object()

    monkeypatch.setattr(env, "FHIREnvironment", unexpected_environment)

    code = cli.main(
        [
            "run-tool",
            str(package_path),
            "--model",
            "provider/model",
        ]
    )

    output = capsys.readouterr().out
    assert code == 2
    assert initialized is False
    assert "strict verification requires asset-manifest.json" in output
    assert "not valid JSON" not in output


def test_run_tool_reports_package_load_failure_without_initializing_cohort(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    initialized = False

    def fail_load(path):
        raise TypeError("malformed package provenance")

    def unexpected_environment(bundles):
        nonlocal initialized
        initialized = True
        return object()

    monkeypatch.setattr(cli, "_load_runtime_package", fail_load)
    monkeypatch.setattr(env, "FHIREnvironment", unexpected_environment)

    code = cli.main(
        [
            "run-tool",
            str(tmp_path / "package"),
            "--model",
            "provider/model",
        ]
    )

    assert code == 2
    assert initialized is False
    assert "cannot load package: malformed package provenance" in capsys.readouterr().out


def test_run_package_reports_package_load_failure_cleanly(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    def fail_load(path):
        raise ValueError("asset hash mismatch for cases.jsonl")

    monkeypatch.setattr(cli, "_load_runtime_package", fail_load)

    code = cli.main(
        [
            "run-package",
            str(tmp_path / "package"),
            "--model",
            "provider/model",
        ]
    )

    assert code == 2
    assert (
        "cannot load package: asset hash mismatch for cases.jsonl"
        in capsys.readouterr().out
    )


def test_run_tool_reports_invalid_cohort_json_cleanly(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    cohort = tmp_path / "case.fhir.json"
    cohort.write_text("{not-json}\n", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "_load_runtime_package",
        lambda path: SimpleNamespace(cohort=[cohort]),
    )

    code = cli.main(
        [
            "run-tool",
            str(tmp_path / "package"),
            "--model",
            "provider/model",
        ]
    )

    assert code == 2
    assert "cannot load package cohort:" in capsys.readouterr().out

"""Non-public scaffold packages fail closed before provider dispatch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from arisekit.benchmark import Benchmark
from arisekit.client import LiteLLMClient, ModelCall, ModelResponse
from arisekit.egress import (
    ProviderDisclosureAuthorization,
    generated_bundle_hash,
)
from arisekit.package import (
    BenchmarkManifest,
    PackageAssetManifest,
    load_package,
    write_package,
)
from arisekit.run_manifest import RunManifest, sha256_digest
from arisekit.scorer import exact_match
from arisekit.sut import SUTResponse, SystemUnderTest
from arisekit.types import BenchmarkItem


ROUTE = "gateway/solver-v1"
PROVIDER = "provider-a"


class _Client:
    model = ROUTE

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, call: ModelCall) -> ModelResponse:
        self.calls += 1
        return ModelResponse(text=str(call.item.ground_truth), cost=0.0)


class _OpaqueSUT(SystemUnderTest):
    name = ROUTE

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, item, **kwargs) -> SUTResponse:
        self.calls += 1
        return SUTResponse(response="yes")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _package(
    tmp_path: Path,
    *,
    release_posture: str = "private",
    classification: str = "synthetic",
    system_prompt: str | None = None,
) -> Path:
    prompt_record = (
        None
        if system_prompt is None
        else {"text": system_prompt, "sha256": sha256_digest(system_prompt)}
    )
    return write_package(
        tmp_path / "package",
        manifest=BenchmarkManifest(
            id="private-fixture",
            name="Private fixture",
            scorer={"kind": "exact-match"},
            provenance={
                "build_spec": {
                    "schema_version": "arisekit.benchmark-build-spec.v1",
                },
                "data_governance": {
                    "classification": classification,
                    "release_posture": release_posture,
                },
                "source": {"system_prompt": prompt_record},
                "first_sweep": [
                    {"model": ROUTE, "provider": PROVIDER, "trials": 1}
                ],
                "readiness": {"allowed_model_routes": [ROUTE]},
            },
        ),
        items=[
            BenchmarkItem(
                id="case-1",
                prompt="Answer yes.",
                ground_truth="yes",
            )
        ],
        write_asset_manifest=True,
    )


def _authorization(
    package: Path,
    *,
    bundle_hash: str | None = None,
    release_posture: str = "private",
) -> ProviderDisclosureAuthorization:
    return ProviderDisclosureAuthorization(
        generated_bundle_hash=bundle_hash or generated_bundle_hash(package),
        access_classification=release_posture,
        solver_providers=(PROVIDER,),
        judge_providers=(),
        authorization_artifact_hash=_hash("owner approval"),
        approved_by="data-owner",
        approved_at="2026-07-27T10:30:00-04:00",
    )


def _install_standard_client(monkeypatch: pytest.MonkeyPatch) -> list[ModelCall]:
    calls: list[ModelCall] = []

    def respond(self, call: ModelCall) -> ModelResponse:
        calls.append(call)
        return ModelResponse(text=str(call.item.ground_truth), cost=0.0)

    monkeypatch.setattr(LiteLLMClient, "__call__", respond)
    return calls


def _package_content_hash(package: Path) -> str:
    loaded = load_package(package, verify_assets=True)
    return sha256_digest([item.to_dict() for item in loaded.items])


def _rewrite_asset_manifest(package: Path) -> None:
    asset_manifest = PackageAssetManifest.build(package)
    (package / "asset-manifest.json").write_text(
        json.dumps(asset_manifest.to_dict()),
        encoding="utf-8",
    )


def test_nonpublic_package_requires_authorization_before_any_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    benchmark = Benchmark.from_package(package)
    calls = _install_standard_client(monkeypatch)
    results_root = tmp_path / "results"

    with pytest.raises(ValueError, match="authorization is required") as exc_info:
        benchmark.run(ROUTE, results_dir=results_root, auto_manifest=True)

    message = str(exc_info.value)
    assert generated_bundle_hash(package) in message
    assert "access_classification='private'" in message
    assert "solver_providers=['provider-a']" in message
    assert calls == []
    assert not results_root.exists()


def test_nonpublic_package_rejects_mismatched_authorization_without_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    benchmark = Benchmark.from_package(package)
    calls = _install_standard_client(monkeypatch)

    with pytest.raises(ValueError, match="generated bundle does not match"):
        benchmark.run(
            ROUTE,
            results_dir=tmp_path / "results",
            provider_authorization=_authorization(
                package,
                bundle_hash=_hash("different bundle"),
            ),
        )

    assert calls == []
    assert not (tmp_path / "results").exists()


def test_matching_authorization_forces_audit_manifest_when_auto_is_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    authorization = _authorization(package)
    calls = _install_standard_client(monkeypatch)

    results = Benchmark.from_package(package).run(
        ROUTE,
        results_dir=tmp_path / "results",
        provider_authorization=authorization,
    )

    assert len(calls) == 1
    manifest_path = results.summary.output_path.parent / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["provider"] == PROVIDER
    assert manifest["model_config"]["route"] == ROUTE
    assert manifest["model_config"]["provider_disclosure"] == {
        "generated_bundle_hash": generated_bundle_hash(package),
        "authorization_digest": authorization.digest,
    }


def test_distinct_authorizations_use_distinct_checkpoint_namespaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    first = _authorization(package)
    second = replace(
        first,
        authorization_artifact_hash=_hash("second owner approval"),
        approved_by="second-data-owner",
    )
    calls = _install_standard_client(monkeypatch)
    benchmark = Benchmark.from_package(package)

    first_results = benchmark.run(
        ROUTE,
        results_dir=tmp_path / "results",
        provider_authorization=first,
    )
    second_results = benchmark.run(
        ROUTE,
        results_dir=tmp_path / "results",
        provider_authorization=second,
    )

    assert len(calls) == 2
    assert first.digest != second.digest
    assert first_results.summary.manifest_digest != second_results.summary.manifest_digest
    assert first_results.summary.output_path.parent != second_results.summary.output_path.parent


def test_caller_manifest_must_bind_exact_authorization_before_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    authorization = _authorization(package)
    calls = _install_standard_client(monkeypatch)
    manifest = RunManifest(
        benchmark_arm="private-fixture",
        benchmark_content_hash=_package_content_hash(package),
        prompt_hash=sha256_digest(""),
        code_hash=_hash("code"),
        model=ROUTE,
        provider=PROVIDER,
        trials=1,
        selection={},
        source_revision="fixture",
        model_config={
            "route": ROUTE,
            "provider_disclosure": {
                "generated_bundle_hash": generated_bundle_hash(package),
                "authorization_digest": _hash("different authorization"),
            }
        },
    )

    with pytest.raises(ValueError, match="does not bind the exact"):
        Benchmark.from_package(package).run(
            ROUTE,
            results_dir=tmp_path / "results",
            provider_authorization=authorization,
            manifest=manifest,
        )

    assert calls == []
    assert not (tmp_path / "results").exists()


def test_matching_caller_manifest_runs_with_reviewed_route_and_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    authorization = _authorization(package)
    calls = _install_standard_client(monkeypatch)
    manifest = RunManifest(
        benchmark_arm="private-fixture",
        benchmark_content_hash=_package_content_hash(package),
        prompt_hash=sha256_digest(""),
        code_hash=_hash("code"),
        model=ROUTE,
        provider=PROVIDER,
        trials=1,
        selection={},
        source_revision="fixture",
        model_config={
            "route": ROUTE,
            "provider_disclosure": {
                "generated_bundle_hash": generated_bundle_hash(package),
                "authorization_digest": authorization.digest,
            },
        },
    )

    results = Benchmark.from_package(package).run(
        ROUTE,
        results_dir=tmp_path / "results",
        provider_authorization=authorization,
        manifest=manifest,
    )

    assert len(calls) == 1
    assert results.summary.manifest_digest == manifest.digest


def test_loaded_package_object_is_reloaded_from_strict_disk_snapshot(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    loaded = load_package(package)
    loaded.items[0].prompt = "Caller-mutated prompt"
    loaded.manifest.provenance["data_governance"]["release_posture"] = "public"

    benchmark = Benchmark.from_package(loaded)

    assert benchmark.dataset[0].prompt == "Answer yes."
    assert benchmark.provider_disclosure_requirement is not None


def test_nonpublic_package_rejects_system_prompt_override(tmp_path: Path) -> None:
    package = _package(tmp_path, system_prompt="Frozen instructions")

    with pytest.raises(ValueError, match="cannot override"):
        Benchmark.from_package(package, system_prompt="Different instructions")

    benchmark = Benchmark.from_package(
        package,
        system_prompt="Frozen instructions",
    )
    assert benchmark.dataset.system_prompt == "Frozen instructions"


def test_post_construction_dataset_mutation_fails_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    benchmark = Benchmark.from_package(package)
    benchmark.dataset._items[0].prompt = "Unauthorized replacement"
    calls = _install_standard_client(monkeypatch)

    with pytest.raises(ValueError, match="dataset content"):
        benchmark.run(
            ROUTE,
            results_dir=tmp_path / "results",
            provider_authorization=_authorization(package),
        )

    assert calls == []
    assert not (tmp_path / "results").exists()


def test_post_construction_prompt_mutation_fails_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path, system_prompt="Frozen instructions")
    benchmark = Benchmark.from_package(package)
    benchmark.dataset.system_prompt = "Unauthorized replacement"
    calls = _install_standard_client(monkeypatch)

    with pytest.raises(ValueError, match="system prompt"):
        benchmark.run(
            ROUTE,
            results_dir=tmp_path / "results",
            provider_authorization=_authorization(package),
        )

    assert calls == []


def test_nonpublic_package_rejects_scorer_override(tmp_path: Path) -> None:
    package = _package(tmp_path)

    with pytest.raises(ValueError, match="scorer overrides"):
        Benchmark.from_package(package, scorer=exact_match())


def test_post_construction_scorer_replacement_fails_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    benchmark = Benchmark.from_package(package)
    benchmark.scorer = exact_match()
    calls = _install_standard_client(monkeypatch)

    with pytest.raises(ValueError, match="canonical deterministic scorer"):
        benchmark.run(
            ROUTE,
            results_dir=tmp_path / "results",
            provider_authorization=_authorization(package),
        )

    assert calls == []


def test_post_construction_scorer_config_mutation_fails_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _package(tmp_path)
    benchmark = Benchmark.from_package(package)
    benchmark.scorer.case_sensitive = True  # type: ignore[attr-defined]
    calls = _install_standard_client(monkeypatch)

    with pytest.raises(ValueError, match="scorer configuration"):
        benchmark.run(
            ROUTE,
            results_dir=tmp_path / "results",
            provider_authorization=_authorization(package),
        )

    assert calls == []


@pytest.mark.parametrize("sut", [_Client(), _OpaqueSUT()])
def test_nonpublic_package_rejects_custom_clients_and_opaque_suts(
    tmp_path: Path,
    sut,
) -> None:
    package = _package(tmp_path)

    with pytest.raises(ValueError, match="standard string-backed"):
        Benchmark.from_package(package).run(
            sut,
            results_dir=tmp_path / "results",
            provider_authorization=_authorization(package),
        )

    assert sut.calls == 0


def test_nonpublic_package_rejects_custom_api_base_before_dispatch(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    client = LiteLLMClient(ROUTE, api_base="https://unapproved.example")

    with pytest.raises(ValueError, match="custom clients, endpoints"):
        Benchmark.from_package(package).run(
            client,
            results_dir=tmp_path / "results",
            provider_authorization=_authorization(package),
        )


def test_nonpublic_governance_cannot_drop_build_spec_marker(tmp_path: Path) -> None:
    package = _package(tmp_path)
    manifest_path = package / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["provenance"]["build_spec"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _rewrite_asset_manifest(package)

    with pytest.raises(ValueError, match="requires the exact"):
        Benchmark.from_package(package)


def test_provider_disclosure_requirement_is_read_only(tmp_path: Path) -> None:
    benchmark = Benchmark.from_package(_package(tmp_path))

    with pytest.raises(AttributeError):
        benchmark.provider_disclosure_requirement = None


def test_public_scaffold_package_remains_authorization_free(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        release_posture="public",
        system_prompt="Frozen public instructions",
    )
    client = _Client()

    benchmark = Benchmark.from_package(package)
    assert benchmark.dataset.system_prompt == "Frozen public instructions"
    results = benchmark.run(
        client,
        results_dir=tmp_path / "results",
        auto_manifest=True,
    )

    assert client.calls == 1
    manifest = json.loads(
        (results.summary.output_path.parent / "run-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert "provider_disclosure" not in manifest["model_config"]


def test_public_v1_rejects_prompt_and_scorer_overrides(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        release_posture="public",
        system_prompt="Frozen public instructions",
    )

    with pytest.raises(ValueError, match="cannot override"):
        Benchmark.from_package(package, system_prompt="Different instructions")
    with pytest.raises(ValueError, match="scorer overrides"):
        Benchmark.from_package(package, scorer=exact_match())


def test_public_v1_requires_asset_manifest(tmp_path: Path) -> None:
    package = _package(tmp_path, release_posture="public")
    (package / "asset-manifest.json").unlink()

    with pytest.raises(ValueError, match="require a verified asset-manifest"):
        Benchmark.from_package(package)


@pytest.mark.parametrize("classification", ["limited", "identifiable"])
def test_v1_rejects_unmaterializable_data_even_with_public_posture(
    tmp_path: Path,
    classification: str,
) -> None:
    package = _package(
        tmp_path,
        release_posture="public",
        classification=classification,
    )

    with pytest.raises(ValueError, match="cannot materialize"):
        Benchmark.from_package(package)


def test_public_posture_rejects_deidentified_classification(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        release_posture="public",
        classification="deidentified",
    )

    with pytest.raises(ValueError, match="public or synthetic"):
        Benchmark.from_package(package)


def test_nonpublic_package_requires_complete_route_provider_mapping(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    manifest_path = package / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"]["readiness"]["allowed_model_routes"].append(
        "gateway/unmapped"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _rewrite_asset_manifest(package)

    with pytest.raises(ValueError, match="mapping is incomplete"):
        Benchmark.from_package(package)

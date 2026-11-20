from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from arisekit.egress import (
    ProviderDisclosureAuthorization,
    generated_bundle_hash,
)
from arisekit.package import BenchmarkManifest, write_package
from arisekit.types import BenchmarkItem


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authorization() -> dict[str, object]:
    return {
        "schema_version": "arisekit.provider-disclosure-authorization.v1",
        "generated_bundle_hash": _hash("bundle"),
        "access_classification": "private",
        "solver_providers": ["solver-b", "solver-a"],
        "judge_providers": ["judge-a", "judge-b"],
        "authorization_artifact_hash": _hash("approval"),
        "approved_by": "data-owner",
        "approved_at": "2026-07-22T12:00:00-04:00",
    }


def test_provider_disclosure_round_trips_canonically_and_binds_exact_sets():
    record = ProviderDisclosureAuthorization.from_dict(_authorization())

    assert record.solver_providers == ("solver-a", "solver-b")
    assert ProviderDisclosureAuthorization.from_dict(record.to_dict()) == record
    assert len(record.digest) == 64
    record.validate_against(
        generated_bundle_hash=_hash("bundle"),
        access_classification="private",
        solver_providers=("solver-b", "solver-a"),
        judge_providers=("judge-b", "judge-a"),
    )


def test_provider_disclosure_allows_no_judge_but_requires_a_solver():
    payload = _authorization()
    payload["judge_providers"] = []

    record = ProviderDisclosureAuthorization.from_dict(payload)

    assert record.judge_providers == ()
    record.validate_against(
        generated_bundle_hash=_hash("bundle"),
        access_classification="private",
        solver_providers=("solver-a", "solver-b"),
        judge_providers=(),
    )

    payload["solver_providers"] = []
    with pytest.raises(ValueError, match="solver_providers.*at least one"):
        ProviderDisclosureAuthorization.from_dict(payload)


def test_provider_disclosure_accepts_held_out_release_posture():
    payload = _authorization()
    payload["access_classification"] = "held-out"
    payload["judge_providers"] = []

    record = ProviderDisclosureAuthorization.from_dict(payload)

    assert record.access_classification == "held-out"


def test_generated_bundle_hash_is_verified_asset_manifest_exact_bytes(
    tmp_path: Path,
):
    package = write_package(
        tmp_path / "package",
        manifest=BenchmarkManifest(id="fixture", name="Fixture"),
        items=[BenchmarkItem(id="case-1", prompt="Q", ground_truth="A")],
        write_asset_manifest=True,
    )
    manifest_bytes = (package / "asset-manifest.json").read_bytes()

    assert generated_bundle_hash(package) == hashlib.sha256(
        manifest_bytes
    ).hexdigest()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("approved_at", "2026-07-22", "RFC 3339"),
        ("approved_by", "", "non-empty"),
        ("authorization_artifact_hash", "not-a-hash", "SHA-256"),
        ("solver_providers", ["same", "SAME"], "distinct"),
    ],
)
def test_provider_disclosure_rejects_malformed_authorization(
    field,
    value,
    message,
):
    payload = _authorization()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        ProviderDisclosureAuthorization.from_dict(payload)


def test_provider_disclosure_rejects_any_changed_disclosure_coordinate():
    record = ProviderDisclosureAuthorization.from_dict(_authorization())

    with pytest.raises(ValueError, match="judge providers does not match"):
        record.validate_against(
            generated_bundle_hash=_hash("bundle"),
            access_classification="private",
            solver_providers=("solver-a", "solver-b"),
            judge_providers=("judge-a", "judge-c"),
        )


def test_provider_disclosure_rejects_unknown_serialized_fields():
    payload = _authorization()
    payload["self_attested"] = True

    with pytest.raises(ValueError, match="unknown"):
        ProviderDisclosureAuthorization.from_dict(payload)

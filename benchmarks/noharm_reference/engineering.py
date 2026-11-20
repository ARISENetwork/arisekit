"""Fail-closed adapter for automated NOHARM engineering candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

from arisekit.run_manifest import sha256_digest

from .adapter import NoHarmBundleError, NoHarmReferenceBundle


ENGINEERING_BUNDLE_MANIFEST_SCHEMA_VERSION = (
    "arisekit.noharm-automated-engineering-bundle.v1"
)
ENGINEERING_CANDIDATE_SCHEMA_VERSION = (
    "arisekit.noharm-automated-engineering-candidate.v1"
)
ENGINEERING_BUNDLE_STATUS = "runnable-engineering-only-human-review-pending"
ENGINEERING_CANDIDATE_STATUS = (
    "synthetic-engineering-complete-human-review-pending"
)
ENGINEERING_CLAIM_SCOPE = "synthetic-engineering-only-not-clinical-validation"
ENGINEERING_PROVENANCE_SCHEMA_VERSION = (
    "arisekit.noharm-engineering-provenance.v1"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class NoHarmEngineeringBundleError(NoHarmBundleError):
    """The bundle is not a hash-bound, human-review-pending candidate."""


class NoHarmEngineeringBundle(NoHarmReferenceBundle):
    """Runnable synthetic bundle that is ineligible for clinical claims.

    The structural NOHARM adapter validates the runnable content. This adapter
    additionally binds that content to the exact automated candidate and freezes
    the non-clinical claim scope used by preliminary solver and judge campaigns.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        candidate_path: str | Path,
        prompt_name: str = "default",
    ):
        unresolved_root = Path(root).expanduser()
        unresolved_candidate = Path(candidate_path).expanduser()
        if unresolved_root.is_symlink():
            raise NoHarmEngineeringBundleError(
                "engineering bundle root must not be a symlink"
            )
        if unresolved_candidate.is_symlink():
            raise NoHarmEngineeringBundleError(
                "engineering candidate must not be a symlink"
            )
        self.candidate_path = unresolved_candidate.resolve()
        self._engineering_manifest: Mapping[str, Any] = MappingProxyType({})
        self._candidate: Mapping[str, Any] = MappingProxyType({})
        self._generation_model_families: tuple[str, ...] = ()
        self._engineering_provenance: Mapping[str, Any] = MappingProxyType({})
        super().__init__(unresolved_root, prompt_name=prompt_name)
        self._load_engineering_binding()

    @property
    def manifest(self) -> Mapping[str, Any]:
        return self._engineering_manifest

    @property
    def candidate(self) -> Mapping[str, Any]:
        return self._candidate

    @property
    def candidate_sha256(self) -> str:
        return str(self._engineering_manifest["candidate"]["sha256"])

    @property
    def generation_model_families(self) -> tuple[str, ...]:
        return self._generation_model_families

    @property
    def engineering_provenance(self) -> Mapping[str, Any]:
        return self._engineering_provenance

    @property
    def engineering_provenance_sha256(self) -> str:
        return sha256_digest(self._engineering_provenance)

    @property
    def access_classification(self) -> str:
        return str(self._engineering_manifest["access"]["classification"])

    def _load_engineering_binding(self) -> None:
        manifest_path = self.root / "engineering-candidate-manifest.json"
        if manifest_path.is_symlink():
            raise NoHarmEngineeringBundleError(
                "engineering candidate manifest must not be a symlink"
            )
        manifest = _read_object(manifest_path, "engineering candidate manifest")
        candidate = _read_object(self.candidate_path, "engineering candidate")

        _require_equal(
            manifest.get("schema_version"),
            ENGINEERING_BUNDLE_MANIFEST_SCHEMA_VERSION,
            "engineering bundle manifest schema",
        )
        _require_equal(
            manifest.get("status"),
            ENGINEERING_BUNDLE_STATUS,
            "engineering bundle status",
        )
        _require_equal(
            manifest.get("claim_scope"),
            ENGINEERING_CLAIM_SCOPE,
            "engineering bundle claim scope",
        )
        human = _object(manifest.get("human_interface"), "human_interface")
        if (
            human.get("used_before_export") is not False
            or human.get("final_human_review_required") is not True
            or human.get("clinical_review_status") != "not_started"
        ):
            raise NoHarmEngineeringBundleError(
                "engineering bundle must remain human-review-pending"
            )

        access = _object(manifest.get("access"), "access")
        if (
            access.get("classification") != "public"
            or access.get("contains_phi") is not False
            or access.get("license") != "CC-BY-4.0"
        ):
            raise NoHarmEngineeringBundleError(
                "engineering bundle access declaration is invalid"
            )

        bundle = _object(manifest.get("bundle"), "bundle")
        expected_bundle = {
            "content_sha256": self.hashes.content_sha256,
            "data_sha256": self.hashes.data_sha256,
            "judge_sha256": self.hashes.judge_sha256,
            "bundle_sha256": self.hashes.bundle_sha256,
            "base_families": self.base_case_count,
            "authored_rows": self.row_count,
            "canonical_evaluated_rows": len(self.select(5)),
        }
        for field, expected in expected_bundle.items():
            _require_equal(bundle.get(field), expected, f"bundle {field}")

        candidate_binding = _object(manifest.get("candidate"), "candidate")
        candidate_name = candidate_binding.get("path")
        candidate_hash = candidate_binding.get("sha256")
        if candidate_name != self.candidate_path.name:
            raise NoHarmEngineeringBundleError(
                "engineering candidate filename does not match the manifest"
            )
        _require_sha256(candidate_hash, "engineering candidate sha256")
        observed_candidate_hash = hashlib.sha256(
            self.candidate_path.read_bytes()
        ).hexdigest()
        if candidate_hash != observed_candidate_hash:
            raise NoHarmEngineeringBundleError(
                "engineering candidate hash does not match the manifest"
            )

        _require_equal(
            candidate.get("schema_version"),
            ENGINEERING_CANDIDATE_SCHEMA_VERSION,
            "engineering candidate schema",
        )
        _require_equal(
            candidate.get("status"),
            ENGINEERING_CANDIDATE_STATUS,
            "engineering candidate status",
        )
        _require_equal(
            candidate.get("claim_scope"),
            ENGINEERING_CLAIM_SCOPE,
            "engineering candidate claim scope",
        )
        candidate_human = _object(
            candidate.get("human_interface"),
            "candidate human_interface",
        )
        if (
            candidate_human.get("final_human_review_required") is not True
            or candidate_human.get("clinical_review_status") != "not_started"
        ):
            raise NoHarmEngineeringBundleError(
                "engineering candidate must remain human-review-pending"
            )
        reference = _object(manifest.get("reference"), "reference")
        candidate_reference = _object(
            candidate.get("reference"),
            "candidate reference",
        )
        _require_sha256(reference.get("bundle_sha256"), "reference bundle sha256")
        _require_equal(
            candidate_reference.get("bundle_sha256"),
            reference["bundle_sha256"],
            "candidate reference bundle sha256",
        )

        topology = _object(candidate.get("topology"), "candidate topology")
        expected_topology = {
            "base_families": self.base_case_count,
            "authored_rows": self.row_count,
            "canonical_evaluated_rows": len(self.select(5)),
        }
        for field, expected in expected_topology.items():
            _require_equal(topology.get(field), expected, f"candidate topology {field}")

        automated_systems = _automated_systems(candidate)
        if manifest.get("automated_systems") != automated_systems:
            raise NoHarmEngineeringBundleError(
                "engineering automated-system provenance does not match the candidate"
            )
        generation_families = tuple(
            row["returned_model"] for row in automated_systems["generator_routes"]
        )
        if not generation_families:
            raise NoHarmEngineeringBundleError(
                "engineering candidate has no bound generation model"
            )
        provenance = {
            "schema_version": ENGINEERING_PROVENANCE_SCHEMA_VERSION,
            "candidate_sha256": candidate_hash,
            "reference_bundle_sha256": reference["bundle_sha256"],
            "bundle_sha256": self.hashes.bundle_sha256,
            "automated_systems": automated_systems,
            "claim_scope": ENGINEERING_CLAIM_SCOPE,
            "release_eligible": False,
        }
        self._engineering_manifest = MappingProxyType(manifest)
        self._candidate = MappingProxyType(candidate)
        self._generation_model_families = generation_families
        self._engineering_provenance = MappingProxyType(provenance)


def automated_systems_for_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical automated-system binding stored in an export."""

    return _automated_systems(candidate)


def _automated_systems(candidate: Mapping[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("automated_evidence")
    if (
        isinstance(evidence, (str, bytes))
        or not isinstance(evidence, Sequence)
        or len(evidence) != 30
    ):
        raise NoHarmEngineeringBundleError(
            "engineering candidate must contain 30 automated evidence records"
        )
    routes: dict[tuple[str, str, str, str], dict[str, str]] = {}
    response_ids: list[str] = []
    for index, record in enumerate(evidence, start=1):
        if not isinstance(record, Mapping):
            raise NoHarmEngineeringBundleError(
                f"automated evidence record {index} must be an object"
            )
        identity = _object(
            record.get("generation_identity"),
            f"automated evidence record {index} generation_identity",
        )
        projected: dict[str, str] = {}
        for field in ("route_id", "provider", "requested_model", "returned_model"):
            value = identity.get(field)
            if not isinstance(value, str) or not value.strip():
                raise NoHarmEngineeringBundleError(
                    f"generation identity {index} has invalid {field}"
                )
            projected[field] = value.strip()
        response_id = identity.get("response_id")
        if not isinstance(response_id, str) or not response_id.strip():
            raise NoHarmEngineeringBundleError(
                f"generation identity {index} has no response id"
            )
        response_ids.append(response_id.strip())
        key = tuple(projected[field] for field in projected)
        routes[key] = projected
    if len(set(response_ids)) != len(response_ids):
        raise NoHarmEngineeringBundleError(
            "engineering generation response ids must be distinct"
        )
    automatic_approval = _object(
        candidate.get("automatic_approval"),
        "candidate automatic_approval",
    )
    critic_routes = automatic_approval.get("critic_routes")
    if not isinstance(critic_routes, list) or len(critic_routes) < 2:
        raise NoHarmEngineeringBundleError(
            "engineering candidate must bind at least two critic routes"
        )
    return {
        "generator_routes": [routes[key] for key in sorted(routes)],
        "generator_response_count": len(response_ids),
        "generator_response_ids_sha256": sha256_digest(sorted(response_ids)),
        "critic_routes": critic_routes,
    }


def _read_object(path: Path, name: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{name} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NoHarmEngineeringBundleError(f"{name} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise NoHarmEngineeringBundleError(f"{name} must be a JSON object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise NoHarmEngineeringBundleError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _reject_constant(value: str) -> Any:
    raise NoHarmEngineeringBundleError(
        f"non-standard JSON number {value!r} is not allowed"
    )


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NoHarmEngineeringBundleError(f"{name} must be an object")
    return value


def _require_equal(observed: Any, expected: Any, name: str) -> None:
    if observed != expected:
        raise NoHarmEngineeringBundleError(f"{name} does not match")


def _require_sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NoHarmEngineeringBundleError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return value


__all__ = [
    "ENGINEERING_BUNDLE_MANIFEST_SCHEMA_VERSION",
    "ENGINEERING_BUNDLE_STATUS",
    "ENGINEERING_CANDIDATE_SCHEMA_VERSION",
    "ENGINEERING_CANDIDATE_STATUS",
    "ENGINEERING_CLAIM_SCOPE",
    "ENGINEERING_PROVENANCE_SCHEMA_VERSION",
    "NoHarmEngineeringBundle",
    "NoHarmEngineeringBundleError",
    "automated_systems_for_candidate",
]

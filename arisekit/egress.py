"""Provider-disclosure authorization for non-public benchmark execution."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from arisekit.common.validate import sha256_hex, text, timestamp


SCHEMA_VERSION = "arisekit.provider-disclosure-authorization.v1"
ACCESS_CLASSIFICATIONS = ("public", "restricted", "private", "held-out")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True)
class ProviderDisclosureAuthorization:
    """A data-owner approval for sending one frozen bundle to exact providers."""

    generated_bundle_hash: str
    access_classification: str
    solver_providers: tuple[str, ...]
    judge_providers: tuple[str, ...]
    authorization_artifact_hash: str
    approved_by: str
    approved_at: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")
        _hash("generated_bundle_hash", self.generated_bundle_hash)
        _hash("authorization_artifact_hash", self.authorization_artifact_hash)
        if self.access_classification not in ACCESS_CLASSIFICATIONS:
            raise ValueError(
                "access_classification must be public, restricted, private, "
                "or held-out"
            )
        object.__setattr__(
            self,
            "solver_providers",
            _providers(
                "solver_providers",
                self.solver_providers,
                allow_empty=False,
            ),
        )
        object.__setattr__(
            self,
            "judge_providers",
            _providers(
                "judge_providers",
                self.judge_providers,
                allow_empty=True,
            ),
        )
        _text("approved_by", self.approved_by)
        _timestamp("approved_at", self.approved_at)

    def validate_against(
        self,
        *,
        generated_bundle_hash: str,
        access_classification: str,
        solver_providers: Sequence[str],
        judge_providers: Sequence[str],
    ) -> None:
        """Reject an authorization that does not match the exact live disclosure."""

        expected_solver = _providers(
            "solver_providers", solver_providers, allow_empty=False
        )
        expected_judge = _providers(
            "judge_providers", judge_providers, allow_empty=True
        )
        checks = (
            (
                "generated bundle",
                self.generated_bundle_hash,
                generated_bundle_hash,
            ),
            (
                "access classification",
                self.access_classification,
                access_classification,
            ),
            ("solver providers", self.solver_providers, expected_solver),
            ("judge providers", self.judge_providers, expected_judge),
        )
        for label, authorized, selected in checks:
            if authorized != selected:
                raise ValueError(
                    f"provider-disclosure authorization {label} does not match "
                    "the selected campaign"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_bundle_hash": self.generated_bundle_hash,
            "access_classification": self.access_classification,
            "solver_providers": list(self.solver_providers),
            "judge_providers": list(self.judge_providers),
            "authorization_artifact_hash": self.authorization_artifact_hash,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "ProviderDisclosureAuthorization":
        fields = {
            "schema_version",
            "generated_bundle_hash",
            "access_classification",
            "solver_providers",
            "judge_providers",
            "authorization_artifact_hash",
            "approved_by",
            "approved_at",
        }
        if not isinstance(data, Mapping):
            raise ValueError("provider-disclosure authorization must be an object")
        missing = fields - set(data)
        unknown = set(data) - fields
        if missing or unknown:
            raise ValueError(
                "invalid provider-disclosure authorization fields; "
                f"missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        for name in ("solver_providers", "judge_providers"):
            value = data[name]
            if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
                raise ValueError(f"{name} must be an array of provider names")
        return cls(
            schema_version=data["schema_version"],
            generated_bundle_hash=data["generated_bundle_hash"],
            access_classification=data["access_classification"],
            solver_providers=tuple(data["solver_providers"]),
            judge_providers=tuple(data["judge_providers"]),
            authorization_artifact_hash=data["authorization_artifact_hash"],
            approved_by=data["approved_by"],
            approved_at=data["approved_at"],
        )

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ProviderDisclosureRequirement:
    """The exact provider disclosure required by one frozen package."""

    generated_bundle_hash: str
    access_classification: str
    route_providers: tuple[tuple[str, str], ...]
    judge_providers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _hash("generated_bundle_hash", self.generated_bundle_hash)
        if self.access_classification not in ACCESS_CLASSIFICATIONS:
            raise ValueError(
                "access_classification must be public, restricted, private, "
                "or held-out"
            )
        routes = tuple(self.route_providers)
        if not routes:
            raise ValueError("route_providers must contain at least one route")
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for index, entry in enumerate(routes):
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise ValueError(
                    f"route_providers[{index}] must be a (route, provider) pair"
                )
            route, provider = entry
            _text(f"route_providers[{index}].route", route)
            _text(f"route_providers[{index}].provider", provider)
            if route in seen:
                raise ValueError(
                    f"route_providers contains duplicate route {route!r}"
                )
            seen.add(route)
            normalized.append((route, provider))
        object.__setattr__(
            self,
            "route_providers",
            tuple(sorted(normalized, key=lambda item: item[0])),
        )
        object.__setattr__(
            self,
            "judge_providers",
            _providers(
                "judge_providers",
                self.judge_providers,
                allow_empty=True,
            ),
        )

    def validate_authorization(
        self,
        *,
        model_route: str,
        authorization: ProviderDisclosureAuthorization | None,
    ) -> None:
        """Validate the selected route before any provider dispatch."""

        provider = self.provider_for_route(model_route)
        expected = self._expected_text(provider)
        if authorization is None:
            raise ValueError(
                "provider-disclosure authorization is required before running "
                f"this non-public benchmark; expected {expected}"
            )
        if not isinstance(authorization, ProviderDisclosureAuthorization):
            raise TypeError(
                "provider_authorization must be a "
                "ProviderDisclosureAuthorization"
            )
        try:
            authorization.validate_against(
                generated_bundle_hash=self.generated_bundle_hash,
                access_classification=self.access_classification,
                solver_providers=(provider,),
                judge_providers=self.judge_providers,
            )
        except ValueError as exc:
            raise ValueError(f"{exc}; expected {expected}") from exc

    def provider_for_route(self, model_route: str) -> str:
        """Return the reviewed provider for an exact model route."""

        provider = dict(self.route_providers).get(model_route)
        if provider is None:
            raise ValueError(
                f"model route {model_route!r} has no provider mapping in the "
                "frozen benchmark package"
            )
        return provider

    def _expected_text(self, provider: str) -> str:
        return (
            f"generated_bundle_hash={self.generated_bundle_hash!r}, "
            f"access_classification={self.access_classification!r}, "
            f"solver_providers={[provider]!r}, "
            f"judge_providers={list(self.judge_providers)!r}"
        )


def generated_bundle_hash(package_root: str | Path) -> str:
    """Hash the exact bytes of a strictly verified package asset manifest."""

    from arisekit.package import ASSET_MANIFEST_FILENAME, load_package

    root = Path(package_root)
    manifest_path = root / ASSET_MANIFEST_FILENAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(
            f"generated bundle requires a regular {ASSET_MANIFEST_FILENAME}"
        )
    before = manifest_path.read_bytes()
    load_package(root, verify_assets=True)
    after = manifest_path.read_bytes()
    if before != after:
        raise ValueError("asset-manifest.json changed during strict verification")
    return hashlib.sha256(before).hexdigest()


def _providers(
    name: str,
    values: Sequence[str],
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be an array of provider names")
    normalized = tuple(values)
    if not normalized and not allow_empty:
        raise ValueError(f"{name} must contain at least one provider")
    for value in normalized:
        _text(name, value)
    if len({value.casefold() for value in normalized}) != len(normalized):
        raise ValueError(f"{name} must contain distinct provider names")
    return tuple(sorted(normalized, key=lambda value: (value.casefold(), value)))


def _hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _text(name: str, value: Any) -> str:
    return text(value, name)


def _timestamp(name: str, value: Any) -> datetime:
    return timestamp(value, name, check_text=lambda v: _text(name, v), pattern=_RFC3339_RE)


__all__ = [
    "ACCESS_CLASSIFICATIONS",
    "ProviderDisclosureAuthorization",
    "ProviderDisclosureRequirement",
    "SCHEMA_VERSION",
    "generated_bundle_hash",
]

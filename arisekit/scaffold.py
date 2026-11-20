"""Deterministic CUJ-02 benchmark scaffolding from a reviewed build sidecar.

The build specification records decisions that were already made through the
authoring skills.  This module does not reinterpret prose or make clinical
choices.  It verifies the source and planning-artifact bytes, normalizes local
JSONL or CSV rows into ``BenchmarkItem`` records, and creates a strict
``BenchmarkPackage`` behind a small Python ``build()`` factory.

Scaffolding and compatibility checks are structural operations.  They do not
run a model, authorize data use, certify clinical quality, or establish MAST
admission.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shlex
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from arisekit.agentic import AGENTIC_PASS_CONDITION_SCHEMA_VERSION
from arisekit.benchmark import Benchmark, Results
from arisekit.common.jsonio import strict_json_loads
from arisekit.common.validate import mapping, number, positive_int, sha256_hex, text
from arisekit.package import (
    AGENTIC_FHIR_ENV_SCHEMA_VERSION,
    AGENTIC_FHIR_ENVIRONMENT,
    ASSET_MANIFEST_FILENAME,
    FHIR_TOOL_CATALOG_VERSION,
    BenchmarkManifest,
    BenchmarkPackage,
    agentic_fhir_binding_from_package,
    load_package,
    multimodal_image_binding_from_package,
    write_package,
)
from arisekit.runner import RunSummary, RunnerConfig
from arisekit.runnable import (
    FILENAME as RUNNABLE_MANIFEST_FILENAME,
    build_manifest_for_directory,
    load_manifest as load_runnable_manifest,
    verify_assets as verify_runnable_assets,
    write_manifest as write_runnable_manifest,
)
from arisekit.types import BenchmarkItem, Metric


BUILD_SPEC_SCHEMA_VERSION = "arisekit.benchmark-build-spec.v1"
AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION = "arisekit.benchmark-build-spec.v2"
MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION = "arisekit.benchmark-build-spec.v3"
IMAGE_ATTACHMENTS_SCHEMA_VERSION = "arisekit.image-attachments.v1"
SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS = frozenset(
    (
        BUILD_SPEC_SCHEMA_VERSION,
        AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION,
        MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION,
    )
)
STRUCTURAL_CLAIM_BOUNDARY = (
    "Structural compatibility only; this does not establish clinical quality, "
    "data authorization, privacy compliance, or MAST admission."
)
EXECUTION_ALLOWLIST_SCOPE = (
    "Reviewed model routes from compliance planning; this is not a "
    "ProviderDisclosureAuthorization."
)

_ARTIFACT_ROLES = (
    "need-statement",
    "existing-coverage",
    "compliance-scope",
    "data-profile",
    "rubric",
    "study-plan",
    "implementation-plan",
)
_PROVENANCE_FIELDS = frozenset(
    (
        "build_spec",
        "source",
        "artifacts",
        "benchmark",
        "runner",
        "smoke_test",
        "first_sweep",
        "readiness",
        "execution_allowlist_scope",
        "data_governance",
        "generated_build_sha256",
    )
)
_SCORER_PRIMITIVES = {
    "exact-match": "arisekit.scorer.exact_match",
    "contains": "arisekit.scorer.contains",
    "choice": "arisekit.scorer.choice",
    "numeric": "arisekit.scorer.numeric",
}
_AGENTIC_SCORER_PRIMITIVE = "arisekit.agentic.PassAtOneScorer"
_SCORER_OPTIONS = {
    "exact-match": frozenset(("case_sensitive", "strip", "name")),
    "contains": frozenset(("case_sensitive", "name")),
    "choice": frozenset(("choices", "case_sensitive", "name")),
    "numeric": frozenset(("atol", "rtol", "name")),
}
_SOURCE_ADAPTER_GAP_PREFIX = "arisekit.scaffold.source-adapter."
_MODALITY_ADAPTER_GAP_PREFIX = "arisekit.scaffold.modality-adapter."
_ATTACHMENT_ADAPTER_GAP_PREFIX = "arisekit.scaffold.attachment-adapter."
_RUNNER_FIELDS = (
    "trials",
    "threads",
    "max_retries",
    "retry_backoff",
    "temperature",
    "max_tokens",
    "max_cost",
    "max_cost_per_call",
    "require_known_cost",
    "max_calls",
)
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")
_SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_RESULTS_CSV_HEADER = (
    "benchmark",
    "model",
    "category",
    "metric",
    "n",
    "value",
    "ci",
)
_DATA_CLASSIFICATIONS = frozenset(
    ("public", "synthetic", "deidentified", "limited", "identifiable")
)
_RELEASE_POSTURES = frozenset(("public", "restricted", "private", "held-out"))
_FHIR_ID_RE = re.compile(r"^[A-Za-z0-9.-]{1,64}$")
_ATTACHMENT_PATH_RE = re.compile(
    r"^attachments/[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.(?:png|jpe?g)$"
)
_ATTACHMENT_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
_MAX_ATTACHMENTS_PER_ITEM = 4
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_MAX_TOTAL_ATTACHMENT_BYTES = 100 * 1024 * 1024


class ScaffoldError(ValueError):
    """Base error for invalid or unsafe scaffold operations."""


class ScaffoldSpecError(ScaffoldError):
    """The versioned benchmark build specification is malformed."""


class ScaffoldLibraryGapError(ScaffoldSpecError):
    """The requested runtime primitive has no supported scaffold adapter."""


def _expected_modality(schema_version: str) -> str:
    """Return the one modality bound by a supported build-spec version."""
    if schema_version == BUILD_SPEC_SCHEMA_VERSION:
        return "text"
    if schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION:
        return "agentic-fhir"
    if schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION:
        return "multimodal"
    raise ScaffoldSpecError(
        f"unsupported schema_version {schema_version!r}; expected one of "
        + ", ".join(sorted(SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS))
    )


@dataclass(frozen=True)
class BenchmarkIdentitySpec:
    name: str
    slug: str
    version: str
    description: str
    mast_category: str
    mast_compatible: bool
    modality: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkIdentitySpec":
        _exact_fields(
            data,
            {
                "name",
                "slug",
                "version",
                "description",
                "mast_category",
                "mast_compatible",
                "modality",
            },
            "benchmark",
        )
        slug = _text(data["slug"], "benchmark.slug")
        _validate_slug(slug)
        version = _text(data["version"], "benchmark.version")
        if not _SEMVER_RE.fullmatch(version):
            raise ScaffoldSpecError(
                "benchmark.version must be a semantic version such as '0.1.0'"
            )
        mast_compatible = data["mast_compatible"]
        if not isinstance(mast_compatible, bool):
            raise ScaffoldSpecError("benchmark.mast_compatible must be boolean")
        modality = _text(data["modality"], "benchmark.modality")
        return cls(
            name=_text(data["name"], "benchmark.name"),
            slug=slug,
            version=version,
            description=_text(data["description"], "benchmark.description"),
            mast_category=_text(data["mast_category"], "benchmark.mast_category"),
            mast_compatible=mast_compatible,
            modality=modality,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slug": self.slug,
            "version": self.version,
            "description": self.description,
            "mast_category": self.mast_category,
            "mast_compatible": self.mast_compatible,
            "modality": self.modality,
        }


@dataclass(frozen=True)
class FieldMapSpec:
    id: str | None
    prompt: str | None
    ground_truth: str | None
    metadata: Mapping[str, str]
    attachments: str | None
    fhir_bundle: str | None = None
    _include_fhir_bundle: bool = field(
        default=False,
        repr=False,
        compare=False,
    )

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        include_fhir_bundle: bool = False,
    ) -> "FieldMapSpec":
        expected_fields = {
            "id",
            "prompt",
            "ground_truth",
            "metadata",
            "attachments",
        }
        if include_fhir_bundle:
            expected_fields.add("fhir_bundle")
        _exact_fields(
            data,
            expected_fields,
            "source.field_map",
        )
        raw_metadata = _object(data["metadata"], "source.field_map.metadata")
        metadata: dict[str, str] = {}
        for output_key, source_key in raw_metadata.items():
            output = _text(output_key, "source.field_map.metadata output key")
            metadata[output] = _text(
                source_key, f"source.field_map.metadata.{output}"
            )
        attachments = _optional_text(
            data["attachments"], "source.field_map.attachments"
        )
        return cls(
            id=_optional_text(data["id"], "source.field_map.id"),
            prompt=_optional_text(data["prompt"], "source.field_map.prompt"),
            ground_truth=_optional_text(
                data["ground_truth"], "source.field_map.ground_truth"
            ),
            metadata={key: metadata[key] for key in sorted(metadata)},
            attachments=attachments,
            fhir_bundle=(
                _optional_text(
                    data["fhir_bundle"],
                    "source.field_map.fhir_bundle",
                )
                if include_fhir_bundle
                else None
            ),
            _include_fhir_bundle=include_fhir_bundle,
        )

    def to_dict(self) -> dict[str, Any]:
        value = {
            "id": self.id,
            "prompt": self.prompt,
            "ground_truth": self.ground_truth,
            "metadata": dict(self.metadata),
            "attachments": self.attachments,
        }
        if self._include_fhir_bundle:
            value["fhir_bundle"] = self.fhir_bundle
        return value


@dataclass(frozen=True)
class SystemPromptSpec:
    text: str
    sha256: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SystemPromptSpec":
        _exact_fields(data, {"text", "sha256"}, "source.system_prompt")
        text = data["text"]
        if not isinstance(text, str):
            raise ScaffoldSpecError(
                "source.system_prompt.text must be a string; use null for an absent prompt"
            )
        return cls(
            text=text,
            sha256=_sha256(data["sha256"], "source.system_prompt.sha256"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"text": self.text, "sha256": self.sha256}


@dataclass(frozen=True)
class SourceSpec:
    kind: str
    path: str | None
    sha256: str | None
    field_map: FieldMapSpec
    system_prompt: SystemPromptSpec | None

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        include_fhir_bundle: bool = False,
    ) -> "SourceSpec":
        _exact_fields(
            data,
            {"kind", "path", "sha256", "field_map", "system_prompt"},
            "source",
        )
        kind = _text(data["kind"], "source.kind")
        raw_prompt = data["system_prompt"]
        prompt = None
        if raw_prompt is not None:
            prompt = SystemPromptSpec.from_dict(
                _object(raw_prompt, "source.system_prompt")
            )
        raw_hash = data["sha256"]
        path = _optional_text(data["path"], "source.path")
        if path is not None:
            _validate_relative_reference(path, "source.path")
        return cls(
            kind=kind,
            path=path,
            sha256=None if raw_hash is None else _sha256(raw_hash, "source.sha256"),
            field_map=FieldMapSpec.from_dict(
                _object(data["field_map"], "source.field_map"),
                include_fhir_bundle=include_fhir_bundle,
            ),
            system_prompt=prompt,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
            "field_map": self.field_map.to_dict(),
            "system_prompt": (
                self.system_prompt.to_dict() if self.system_prompt else None
            ),
        }


@dataclass(frozen=True)
class ScorerSpec:
    kind: str
    primitive: str
    options: Mapping[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScorerSpec":
        _exact_fields(data, {"kind", "primitive", "options"}, "scorer")
        kind = _text(data["kind"], "scorer.kind")
        primitive = _text(data["primitive"], "scorer.primitive")
        options = _canonical_json(_object(data["options"], "scorer.options"), "scorer.options")
        if kind == "rubric-judge":
            from arisekit.judges.rubric import validate_rubric
            if primitive != "arisekit.judges.rubric.RubricJudge" or set(options) != {"rubric"}:
                raise ScaffoldSpecError("rubric-judge requires the versioned RubricJudge adapter")
            try:
                validate_rubric(options["rubric"])
            except (TypeError, ValueError) as exc:
                raise ScaffoldSpecError(str(exc)) from exc
        elif kind in _SCORER_PRIMITIVES:
            expected = _SCORER_PRIMITIVES[kind]
            if primitive != expected:
                raise ScaffoldSpecError(
                    f"scorer primitive {primitive!r} does not match {kind!r}; expected {expected!r}"
                )
            _validate_scorer_options(kind, options)
        elif kind == "pass-at-one":
            if primitive != _AGENTIC_SCORER_PRIMITIVE:
                raise ScaffoldSpecError(
                    f"scorer primitive {primitive!r} does not match "
                    f"'pass-at-one'; expected {_AGENTIC_SCORER_PRIMITIVE!r}"
                )
            _exact_fields(
                options,
                {"name", "condition_schema"},
                "scorer.options",
            )
            if _text(options["name"], "scorer.options.name") != "pass_at_1":
                raise ScaffoldSpecError(
                    "scorer.options.name must be 'pass_at_1' for build-spec v2"
                )
            if (
                _text(
                    options["condition_schema"],
                    "scorer.options.condition_schema",
                )
                != AGENTIC_PASS_CONDITION_SCHEMA_VERSION
            ):
                raise ScaffoldSpecError(
                    "scorer.options.condition_schema must be "
                    f"{AGENTIC_PASS_CONDITION_SCHEMA_VERSION!r}"
                )
        return cls(kind=kind, primitive=primitive, options=options)

    @property
    def auto_bindable(self) -> bool:
        return self.kind == "rubric-judge" or self.kind in _SCORER_PRIMITIVES or (
            self.kind == "pass-at-one"
            and self.primitive == _AGENTIC_SCORER_PRIMITIVE
            and self.options.get("condition_schema")
            == AGENTIC_PASS_CONDITION_SCHEMA_VERSION
        )

    def manifest_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, **dict(self.options)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "primitive": self.primitive,
            "options": _canonical_json(self.options, "scorer.options"),
        }


@dataclass(frozen=True)
class RunnerBuildSpec:
    trials: int
    threads: int
    max_retries: int
    retry_backoff: float
    temperature: float | None
    max_tokens: int | None
    max_cost: float | None
    max_cost_per_call: float | None
    require_known_cost: bool
    max_calls: int | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunnerBuildSpec":
        _exact_fields(data, set(_RUNNER_FIELDS), "runner")
        require_known_cost = data["require_known_cost"]
        if not isinstance(require_known_cost, bool):
            raise ScaffoldSpecError("runner.require_known_cost must be boolean")
        spec = cls(
            trials=_positive_int(data["trials"], "runner.trials"),
            threads=_positive_int(data["threads"], "runner.threads"),
            max_retries=_positive_int(
                data["max_retries"], "runner.max_retries"
            ),
            retry_backoff=_finite_number(
                data["retry_backoff"], "runner.retry_backoff", minimum=0.0
            ),
            temperature=_optional_finite_number(
                data["temperature"], "runner.temperature"
            ),
            max_tokens=_optional_positive_int(
                data["max_tokens"], "runner.max_tokens"
            ),
            max_cost=_optional_finite_number(
                data["max_cost"], "runner.max_cost", exclusive_minimum=0.0
            ),
            max_cost_per_call=_optional_finite_number(
                data["max_cost_per_call"],
                "runner.max_cost_per_call",
                exclusive_minimum=0.0,
            ),
            require_known_cost=require_known_cost,
            max_calls=_optional_positive_int(data["max_calls"], "runner.max_calls"),
        )
        if (
            spec.max_cost is not None
            and spec.max_cost_per_call is not None
            and spec.max_cost_per_call > spec.max_cost
        ):
            raise ScaffoldSpecError(
                "runner.max_cost_per_call cannot exceed runner.max_cost"
            )
        return spec

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _RUNNER_FIELDS}

    def as_runner_config(self) -> RunnerConfig:
        return RunnerConfig(**self.to_dict())


@dataclass(frozen=True)
class SmokeTestSpec:
    model: str
    limit: int
    trials: int

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SmokeTestSpec":
        _exact_fields(data, {"model", "limit", "trials"}, "smoke_test")
        return cls(
            model=_single_line_text(data["model"], "smoke_test.model"),
            limit=_positive_int(data["limit"], "smoke_test.limit"),
            trials=_positive_int(data["trials"], "smoke_test.trials"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "limit": self.limit, "trials": self.trials}


@dataclass(frozen=True)
class SweepModelSpec:
    model: str
    provider: str
    trials: int

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], index: int) -> "SweepModelSpec":
        label = f"first_sweep[{index}]"
        _exact_fields(data, {"model", "provider", "trials"}, label)
        return cls(
            model=_single_line_text(data["model"], f"{label}.model"),
            provider=_single_line_text(data["provider"], f"{label}.provider"),
            trials=_positive_int(data["trials"], f"{label}.trials"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "provider": self.provider, "trials": self.trials}


@dataclass(frozen=True)
class ArtifactSpec:
    role: str
    path: str | None
    sha256: str | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], index: int) -> "ArtifactSpec":
        label = f"artifacts[{index}]"
        _exact_fields(data, {"role", "path", "sha256"}, label)
        raw_hash = data["sha256"]
        path = _optional_text(data["path"], f"{label}.path")
        if path is not None:
            _validate_relative_reference(path, f"{label}.path")
        return cls(
            role=_text(data["role"], f"{label}.role"),
            path=path,
            sha256=None if raw_hash is None else _sha256(raw_hash, f"{label}.sha256"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class LibraryGapSpec:
    primitive: str
    reason: str
    owner_or_issue: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], index: int) -> "LibraryGapSpec":
        label = f"readiness.library_gaps[{index}]"
        _exact_fields(data, {"primitive", "reason", "owner_or_issue"}, label)
        return cls(
            primitive=_text(data["primitive"], f"{label}.primitive"),
            reason=_text(data["reason"], f"{label}.reason"),
            owner_or_issue=_text(data["owner_or_issue"], f"{label}.owner_or_issue"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "primitive": self.primitive,
            "reason": self.reason,
            "owner_or_issue": self.owner_or_issue,
        }


@dataclass(frozen=True)
class UserConfirmationSpec:
    actor: str
    confirmed_at: str
    text: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UserConfirmationSpec":
        _exact_fields(data, {"actor", "confirmed_at", "text"}, "readiness.user_confirmation")
        return cls(
            actor=_text(data["actor"], "readiness.user_confirmation.actor"),
            confirmed_at=_text(
                data["confirmed_at"], "readiness.user_confirmation.confirmed_at"
            ),
            text=_text(data["text"], "readiness.user_confirmation.text"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "actor": self.actor,
            "confirmed_at": self.confirmed_at,
            "text": self.text,
        }


@dataclass(frozen=True)
class ReadinessSpec:
    status: str
    data_profile: str
    allowed_model_routes: tuple[str, ...]
    library_gaps: tuple[LibraryGapSpec, ...]
    open_questions: tuple[str, ...]
    user_confirmation: UserConfirmationSpec | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReadinessSpec":
        _exact_fields(
            data,
            {
                "status",
                "data_profile",
                "allowed_model_routes",
                "library_gaps",
                "open_questions",
                "user_confirmation",
            },
            "readiness",
        )
        status = _text(data["status"], "readiness.status")
        if status not in ("ready", "blocked"):
            raise ScaffoldSpecError("readiness.status must be 'ready' or 'blocked'")
        raw_routes = _list(data["allowed_model_routes"], "readiness.allowed_model_routes")
        routes = tuple(
            _single_line_text(value, f"readiness.allowed_model_routes[{index}]")
            for index, value in enumerate(raw_routes)
        )
        if len(set(routes)) != len(routes):
            raise ScaffoldSpecError("readiness.allowed_model_routes contains duplicates")
        raw_gaps = _list(data["library_gaps"], "readiness.library_gaps")
        gaps = tuple(
            LibraryGapSpec.from_dict(_object(value, f"readiness.library_gaps[{index}]"), index)
            for index, value in enumerate(raw_gaps)
        )
        raw_questions = _list(data["open_questions"], "readiness.open_questions")
        questions = tuple(
            _text(value, f"readiness.open_questions[{index}]")
            for index, value in enumerate(raw_questions)
        )
        raw_confirmation = data["user_confirmation"]
        confirmation = None
        if raw_confirmation is not None:
            confirmation = UserConfirmationSpec.from_dict(
                _object(raw_confirmation, "readiness.user_confirmation")
            )
        return cls(
            status=status,
            data_profile=_text(data["data_profile"], "readiness.data_profile"),
            allowed_model_routes=routes,
            library_gaps=gaps,
            open_questions=questions,
            user_confirmation=confirmation,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data_profile": self.data_profile,
            "allowed_model_routes": list(self.allowed_model_routes),
            "library_gaps": [gap.to_dict() for gap in self.library_gaps],
            "open_questions": list(self.open_questions),
            "user_confirmation": (
                self.user_confirmation.to_dict() if self.user_confirmation else None
            ),
        }


@dataclass(frozen=True)
class MaterializationAuthorizationSpec:
    authorized: bool
    actor: str | None
    confirmed_at: str | None
    text: str | None

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "MaterializationAuthorizationSpec":
        label = "data_governance.materialization_authorization"
        _exact_fields(data, {"authorized", "actor", "confirmed_at", "text"}, label)
        authorized = data["authorized"]
        if not isinstance(authorized, bool):
            raise ScaffoldSpecError(f"{label}.authorized must be boolean")
        actor = _optional_text(data["actor"], f"{label}.actor")
        confirmed_at = _optional_text(
            data["confirmed_at"], f"{label}.confirmed_at"
        )
        text = _optional_text(data["text"], f"{label}.text")
        if not authorized:
            if actor is None or confirmed_at is None or text is None:
                raise ScaffoldSpecError(
                    f"{label} refusal must include actor, confirmed_at, and "
                    "verbatim text"
                )
            if not _is_rfc3339(confirmed_at):
                raise ScaffoldSpecError(
                    f"{label}.confirmed_at must be RFC 3339 for a refusal"
                )
        return cls(
            authorized=authorized,
            actor=actor,
            confirmed_at=confirmed_at,
            text=text,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "actor": self.actor,
            "confirmed_at": self.confirmed_at,
            "text": self.text,
        }


@dataclass(frozen=True)
class DataGovernanceSpec:
    classification: str
    release_posture: str
    materialization_authorization: MaterializationAuthorizationSpec

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DataGovernanceSpec":
        _exact_fields(
            data,
            {
                "classification",
                "release_posture",
                "materialization_authorization",
            },
            "data_governance",
        )
        classification = _text(
            data["classification"], "data_governance.classification"
        )
        if classification not in _DATA_CLASSIFICATIONS:
            raise ScaffoldSpecError(
                "data_governance.classification must be public, synthetic, "
                "deidentified, limited, or identifiable"
            )
        release_posture = _text(
            data["release_posture"], "data_governance.release_posture"
        )
        if release_posture not in _RELEASE_POSTURES:
            raise ScaffoldSpecError(
                "data_governance.release_posture must be public, restricted, "
                "private, or held-out"
            )
        return cls(
            classification=classification,
            release_posture=release_posture,
            materialization_authorization=MaterializationAuthorizationSpec.from_dict(
                _object(
                    data["materialization_authorization"],
                    "data_governance.materialization_authorization",
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "release_posture": self.release_posture,
            "materialization_authorization": self.materialization_authorization.to_dict(),
        }


@dataclass(frozen=True)
class AgenticEnvironmentSpec:
    kind: str
    primitive: str
    fhir_version: str
    isolation: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgenticEnvironmentSpec":
        _exact_fields(
            data,
            {"kind", "primitive", "fhir_version", "isolation"},
            "agentic.environment",
        )
        value = cls(
            kind=_text(data["kind"], "agentic.environment.kind"),
            primitive=_text(
                data["primitive"], "agentic.environment.primitive"
            ),
            fhir_version=_text(
                data["fhir_version"], "agentic.environment.fhir_version"
            ),
            isolation=_text(
                data["isolation"], "agentic.environment.isolation"
            ),
        )
        expected = cls(**AGENTIC_FHIR_ENVIRONMENT)
        if value != expected:
            raise ScaffoldSpecError(
                "agentic.environment must bind the ARISEKit in-memory FHIR R4 "
                "environment with per-item-trial isolation"
            )
        return value

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "primitive": self.primitive,
            "fhir_version": self.fhir_version,
            "isolation": self.isolation,
        }


@dataclass(frozen=True)
class AgenticFHIRSpec:
    environment: AgenticEnvironmentSpec
    tool_catalog: str
    allowed_tools: tuple[str, ...]
    max_turns: int

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgenticFHIRSpec":
        _exact_fields(
            data,
            {"environment", "tool_catalog", "allowed_tools", "max_turns"},
            "agentic",
        )
        catalog = _text(data["tool_catalog"], "agentic.tool_catalog")
        if catalog != FHIR_TOOL_CATALOG_VERSION:
            raise ScaffoldSpecError(
                f"agentic.tool_catalog must be {FHIR_TOOL_CATALOG_VERSION!r}"
            )
        raw_tools = _list(data["allowed_tools"], "agentic.allowed_tools")
        tools = tuple(
            _single_line_text(value, f"agentic.allowed_tools[{index}]")
            for index, value in enumerate(raw_tools)
        )
        if not tools:
            raise ScaffoldSpecError("agentic.allowed_tools must not be empty")
        if len(tools) != len(set(tools)):
            raise ScaffoldSpecError("agentic.allowed_tools contains duplicates")
        known_tools = set(_fhir_tool_schema_map())
        unknown = sorted(set(tools) - known_tools)
        if unknown:
            raise ScaffoldSpecError(
                "agentic.allowed_tools contains unknown tools: "
                + ", ".join(unknown)
            )
        return cls(
            environment=AgenticEnvironmentSpec.from_dict(
                _object(data["environment"], "agentic.environment")
            ),
            tool_catalog=catalog,
            allowed_tools=tools,
            max_turns=_positive_int(data["max_turns"], "agentic.max_turns"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment.to_dict(),
            "tool_catalog": self.tool_catalog,
            "allowed_tools": list(self.allowed_tools),
            "max_turns": self.max_turns,
        }


@dataclass(frozen=True)
class ImageAttachmentAssetSpec:
    path: str
    sha256: str
    size_bytes: int
    media_type: str

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        index: int,
    ) -> "ImageAttachmentAssetSpec":
        label = f"multimodal.assets[{index}]"
        _exact_fields(
            data,
            {"path", "sha256", "size_bytes", "media_type"},
            label,
        )
        path = _text(data["path"], f"{label}.path")
        if not _ATTACHMENT_PATH_RE.fullmatch(path):
            raise ScaffoldSpecError(
                f"{label}.path must be a flat PNG or JPEG path under attachments/"
            )
        suffix = PurePosixPath(path).suffix
        media_type = _text(data["media_type"], f"{label}.media_type")
        expected_media_type = _ATTACHMENT_MEDIA_TYPES[suffix]
        if media_type != expected_media_type:
            raise ScaffoldSpecError(
                f"{label}.media_type must be {expected_media_type!r} for {suffix}"
            )
        size = data["size_bytes"]
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or size > _MAX_ATTACHMENT_BYTES
        ):
            raise ScaffoldSpecError(
                f"{label}.size_bytes must be between 1 and "
                f"{_MAX_ATTACHMENT_BYTES}"
            )
        return cls(
            path=path,
            sha256=_sha256(data["sha256"], f"{label}.sha256"),
            size_bytes=size,
            media_type=media_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


@dataclass(frozen=True)
class MultimodalImageSpec:
    assets: tuple[ImageAttachmentAssetSpec, ...]
    schema_version: str = IMAGE_ATTACHMENTS_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MultimodalImageSpec":
        _exact_fields(data, {"schema_version", "assets"}, "multimodal")
        schema_version = _text(
            data["schema_version"], "multimodal.schema_version"
        )
        if schema_version != IMAGE_ATTACHMENTS_SCHEMA_VERSION:
            raise ScaffoldSpecError(
                "multimodal.schema_version must be "
                f"{IMAGE_ATTACHMENTS_SCHEMA_VERSION!r}"
            )
        raw_assets = _list(data["assets"], "multimodal.assets")
        assets = tuple(
            ImageAttachmentAssetSpec.from_dict(
                _object(value, f"multimodal.assets[{index}]"),
                index,
            )
            for index, value in enumerate(raw_assets)
        )
        paths = [asset.path for asset in assets]
        if paths != sorted(paths):
            raise ScaffoldSpecError(
                "multimodal.assets must be lexicographically ordered by path"
            )
        if len(paths) != len(set(paths)):
            raise ScaffoldSpecError("multimodal.assets contains duplicate paths")
        folded = [path.casefold() for path in paths]
        if len(folded) != len(set(folded)):
            raise ScaffoldSpecError(
                "multimodal.assets contains case-insensitive duplicate paths"
            )
        if sum(asset.size_bytes for asset in assets) > _MAX_TOTAL_ATTACHMENT_BYTES:
            raise ScaffoldSpecError(
                "multimodal.assets exceeds the 100 MiB aggregate limit"
            )
        return cls(assets=assets, schema_version=schema_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "assets": [asset.to_dict() for asset in self.assets],
        }


@dataclass(frozen=True)
class BenchmarkScaffoldSpec:
    """A strict, versioned plan-to-runnable benchmark build contract."""

    benchmark: BenchmarkIdentitySpec
    source: SourceSpec
    scorer: ScorerSpec
    runner: RunnerBuildSpec
    smoke_test: SmokeTestSpec
    first_sweep: tuple[SweepModelSpec, ...]
    artifacts: tuple[ArtifactSpec, ...]
    readiness: ReadinessSpec
    data_governance: DataGovernanceSpec
    agentic: AgenticFHIRSpec | None = None
    multimodal: MultimodalImageSpec | None = None
    schema_version: str = BUILD_SPEC_SCHEMA_VERSION
    _base_dir: Path = field(default_factory=lambda: Path.cwd().resolve(), repr=False, compare=False)
    _source_path: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS:
            raise ScaffoldSpecError(
                f"unsupported schema_version {self.schema_version!r}; "
                "expected one of "
                + ", ".join(sorted(SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS))
            )
        object.__setattr__(self, "_base_dir", self._base_dir.resolve())
        self._validate_contract()

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        base_dir: str | Path | None = None,
    ) -> "BenchmarkScaffoldSpec":
        schema_version = _text(data.get("schema_version"), "schema_version")
        if schema_version not in SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS:
            raise ScaffoldSpecError(
                f"unsupported schema_version {schema_version!r}; expected one of "
                + ", ".join(sorted(SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS))
            )
        expected_fields = {
            "schema_version",
            "benchmark",
            "source",
            "scorer",
            "runner",
            "smoke_test",
            "first_sweep",
            "artifacts",
            "readiness",
            "data_governance",
        }
        is_agentic_v2 = schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION
        is_multimodal_v3 = schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION
        if is_agentic_v2:
            expected_fields.add("agentic")
        if is_multimodal_v3:
            expected_fields.add("multimodal")
        _exact_fields(
            data,
            expected_fields,
            "build spec",
        )
        raw_sweep = _list(data["first_sweep"], "first_sweep")
        raw_artifacts = _list(data["artifacts"], "artifacts")
        return cls(
            schema_version=schema_version,
            benchmark=BenchmarkIdentitySpec.from_dict(
                _object(data["benchmark"], "benchmark")
            ),
            source=SourceSpec.from_dict(
                _object(data["source"], "source"),
                include_fhir_bundle=is_agentic_v2,
            ),
            scorer=ScorerSpec.from_dict(_object(data["scorer"], "scorer")),
            runner=RunnerBuildSpec.from_dict(_object(data["runner"], "runner")),
            smoke_test=SmokeTestSpec.from_dict(
                _object(data["smoke_test"], "smoke_test")
            ),
            first_sweep=tuple(
                SweepModelSpec.from_dict(_object(value, f"first_sweep[{index}]"), index)
                for index, value in enumerate(raw_sweep)
            ),
            artifacts=tuple(
                ArtifactSpec.from_dict(_object(value, f"artifacts[{index}]"), index)
                for index, value in enumerate(raw_artifacts)
            ),
            readiness=ReadinessSpec.from_dict(
                _object(data["readiness"], "readiness")
            ),
            data_governance=DataGovernanceSpec.from_dict(
                _object(data["data_governance"], "data_governance")
            ),
            agentic=(
                AgenticFHIRSpec.from_dict(
                    _object(data["agentic"], "agentic")
                )
                if is_agentic_v2
                else None
            ),
            multimodal=(
                MultimodalImageSpec.from_dict(
                    _object(data["multimodal"], "multimodal")
                )
                if is_multimodal_v3
                else None
            ),
            _base_dir=Path(base_dir or Path.cwd()).expanduser().resolve(),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "BenchmarkScaffoldSpec":
        unresolved = Path(path).expanduser()
        if unresolved.is_symlink():
            raise ScaffoldSpecError(f"build spec cannot be a symlink: {unresolved}")
        source = unresolved.resolve()
        if not source.is_file():
            raise ScaffoldSpecError(f"build spec is not a regular file: {source}")
        try:
            payload = _strict_json_load(source)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ScaffoldSpecError(f"cannot read build spec {source}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ScaffoldSpecError(f"build spec {source} must contain an object")
        spec = cls.from_dict(payload, base_dir=source.parent)
        object.__setattr__(spec, "_source_path", source)
        return spec

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark.to_dict(),
            "source": self.source.to_dict(),
            "scorer": self.scorer.to_dict(),
            "runner": self.runner.to_dict(),
            "smoke_test": self.smoke_test.to_dict(),
            "first_sweep": [entry.to_dict() for entry in self.first_sweep],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "readiness": self.readiness.to_dict(),
            "data_governance": self.data_governance.to_dict(),
        }
        if self.schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION:
            value["agentic"] = self.agentic.to_dict() if self.agentic else None
        if self.schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION:
            value["multimodal"] = (
                self.multimodal.to_dict() if self.multimodal else None
            )
        return value

    @property
    def source_path(self) -> Path | None:
        return _resolve_optional_path(self.source.path, self._base_dir)

    def artifact_path(self, artifact: ArtifactSpec) -> Path | None:
        return _resolve_optional_path(artifact.path, self._base_dir)

    def attachment_path(self, asset: ImageAttachmentAssetSpec) -> Path:
        path = _resolve_optional_path(asset.path, self._base_dir)
        assert path is not None
        return path

    def _validate_contract(self) -> None:
        is_agentic_v2 = (
            self.schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION
        )
        is_multimodal_v3 = (
            self.schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION
        )
        roles = [artifact.role for artifact in self.artifacts]
        expected_roles = set(_ARTIFACT_ROLES)
        if len(roles) != len(set(roles)) or set(roles) != expected_roles:
            raise ScaffoldSpecError(
                "artifacts must contain each required role exactly once; "
                f"missing={sorted(expected_roles - set(roles))}, "
                f"extra={sorted(set(roles) - expected_roles)}, duplicates={_duplicates(roles)}"
            )
        if not self.first_sweep:
            raise ScaffoldSpecError("first_sweep must contain at least one model")
        models = [entry.model for entry in self.first_sweep]
        if len(models) != len(set(models)):
            raise ScaffoldSpecError("first_sweep contains duplicate model routes")
        blockers: list[str] = []
        if self.readiness.data_profile != "materialized":
            blockers.append("readiness.data_profile is not 'materialized'")
        supported_sources = (
            ("jsonl",)
            if is_agentic_v2 or is_multimodal_v3
            else ("jsonl", "csv")
        )
        if self.source.kind not in supported_sources:
            if is_agentic_v2 or is_multimodal_v3:
                adapter = "v2" if is_agentic_v2 else "v3"
                blockers.append(
                    f"source kind {self.source.kind!r} has no build-spec {adapter} adapter"
                )
            else:
                blockers.append(
                    f"source kind {self.source.kind!r} has no build-spec v1 adapter"
                )
        expected_modality = _expected_modality(self.schema_version)
        if self.benchmark.modality != expected_modality:
            if is_agentic_v2:
                blockers.append(
                    f"benchmark modality {self.benchmark.modality!r} has no "
                    "build-spec v2 agentic-fhir adapter"
                )
            elif is_multimodal_v3:
                blockers.append(
                    f"benchmark modality {self.benchmark.modality!r} has no "
                    "build-spec v3 multimodal adapter"
                )
            else:
                blockers.append(
                    f"benchmark modality {self.benchmark.modality!r} has no "
                    "build-spec v1 adapter"
                )
        if is_agentic_v2 and self.agentic is None:
            blockers.append("agentic configuration is required for build-spec v2")
        if not is_agentic_v2 and self.agentic is not None:
            blockers.append(
                "agentic configuration is allowed only in build-spec v2"
            )
        if is_multimodal_v3 and self.multimodal is None:
            blockers.append("multimodal configuration is required for build-spec v3")
        if not is_multimodal_v3 and self.multimodal is not None:
            blockers.append(
                "multimodal configuration is allowed only in build-spec v3"
            )
        if self.source.path is None or self.source.sha256 is None:
            blockers.append("source.path and source.sha256 are required")
        field_map = self.source.field_map
        if field_map.id is None or field_map.prompt is None or field_map.ground_truth is None:
            blockers.append("source.field_map id, prompt, and ground_truth are required")
        if is_multimodal_v3 and field_map.attachments != "attachments":
            blockers.append(
                "source.field_map.attachments must be 'attachments' for build-spec v3"
            )
        elif not is_multimodal_v3 and field_map.attachments is not None:
            blockers.append(
                "source.field_map.attachments must be null because this adapter "
                "does not copy or hash attachment assets"
            )
        if is_agentic_v2 and field_map.fhir_bundle != "fhir_bundle":
            blockers.append(
                "source.field_map.fhir_bundle must be 'fhir_bundle' for "
                "build-spec v2"
            )
        if any(artifact.path is None or artifact.sha256 is None for artifact in self.artifacts):
            blockers.append("every planning artifact needs a path and SHA-256")
        if is_multimodal_v3 and (
            self.multimodal is None or not self.multimodal.assets
        ):
            blockers.append("multimodal.assets must contain at least one image")
        if is_agentic_v2 and self.scorer.kind not in {"pass-at-one", "rubric-judge"}:
            blockers.append(
                "build-spec v2 agentic-fhir requires the versioned pass-at-one scorer"
            )
        elif is_multimodal_v3 and self.scorer.kind not in {"exact-match", "rubric-judge"}:
            blockers.append(
                "build-spec v3 multimodal requires exact-match for its "
                "structural attachment smoke"
            )
        elif not is_agentic_v2 and self.scorer.kind == "pass-at-one":
            blockers.append(
                f"{self.schema_version} does not support pass-at-one scoring"
            )
        elif not self.scorer.auto_bindable:
            adapter = "v2" if is_agentic_v2 else ("v3" if is_multimodal_v3 else "v1")
            blockers.append(
                f"scorer {self.scorer.primitive!r} has no {adapter} scaffold adapter"
            )
        if self.readiness.library_gaps:
            blockers.append("readiness.library_gaps is not empty")
        if self.readiness.open_questions:
            blockers.append("readiness.open_questions is not empty")
        if self.smoke_test.model not in self.readiness.allowed_model_routes:
            blockers.append("smoke-test model is not in allowed_model_routes")
        disallowed_sweep = sorted(
            set(models) - set(self.readiness.allowed_model_routes)
        )
        if disallowed_sweep:
            blockers.append(
                "first-sweep models are not in allowed_model_routes: "
                + ", ".join(disallowed_sweep)
            )
        missing_sweep = sorted(
            set(self.readiness.allowed_model_routes) - set(models)
        )
        if missing_sweep:
            blockers.append(
                "allowed_model_routes are missing from first_sweep: "
                + ", ".join(missing_sweep)
            )
        if self.readiness.user_confirmation is None:
            blockers.append("readiness.user_confirmation is missing")
        elif not _is_rfc3339(self.readiness.user_confirmation.confirmed_at):
            blockers.append("readiness.user_confirmation.confirmed_at is not RFC 3339")
        if not self.benchmark.mast_compatible:
            blockers.append("benchmark.mast_compatible is false")
        governance = self.data_governance
        authorization = governance.materialization_authorization
        if self.scorer.kind == "rubric-judge" and (governance.classification not in {"public", "synthetic"} or governance.release_posture != "public"):
            blockers.append("rubric judging currently requires public or synthetic data with public release posture")
        if is_agentic_v2 and (
            governance.classification not in ("public", "synthetic")
            or governance.release_posture != "public"
        ):
            blockers.append(
                "the initial agentic-fhir adapter requires public or synthetic "
                "data with a public release posture"
            )
        if is_multimodal_v3 and (
            governance.classification not in ("public", "synthetic")
            or governance.release_posture != "public"
        ):
            blockers.append(
                "the initial multimodal adapter requires public or synthetic "
                "data with a public release posture"
            )
        if governance.classification in ("limited", "identifiable"):
            blockers.append(
                f"data classification {governance.classification!r} cannot be "
                "materialized by build-spec v1"
            )
        if governance.release_posture == "public" and governance.classification not in (
            "public",
            "synthetic",
        ):
            blockers.append(
                "public release posture requires public or synthetic classification"
            )
        if not authorization.authorized:
            blockers.append("materialization authorization is false")
        if not authorization.actor or not authorization.confirmed_at or not authorization.text:
            blockers.append("materialization authorization actor, time, and text are required")
        elif not _is_rfc3339(authorization.confirmed_at):
            blockers.append(
                "materialization authorization confirmed_at is not RFC 3339"
            )
        if self.readiness.status == "ready" and blockers:
            raise ScaffoldSpecError(
                "readiness.status is 'ready' but readiness gates fail: "
                + "; ".join(blockers)
            )
        if self.readiness.status == "blocked":
            gaps = self.readiness.library_gaps
            gap_primitives = {gap.primitive for gap in gaps}
            required_gaps: list[tuple[str, str]] = []
            if self.source.kind not in supported_sources:
                required_gaps.append(
                    (
                        "source kind",
                        _SOURCE_ADAPTER_GAP_PREFIX + self.source.kind,
                    )
                )
            if self.benchmark.modality != expected_modality:
                required_gaps.append(
                    (
                        "benchmark modality",
                        _MODALITY_ADAPTER_GAP_PREFIX + self.benchmark.modality,
                    )
                )
            if (
                not is_multimodal_v3 and field_map.attachments is not None
            ):
                required_gaps.append(
                    (
                        "attachment mapping",
                        _ATTACHMENT_ADAPTER_GAP_PREFIX + field_map.attachments,
                    )
                )
            if not self.scorer.auto_bindable:
                required_gaps.append(("scorer", self.scorer.primitive))
            missing_gaps = [
                (adapter, primitive)
                for adapter, primitive in required_gaps
                if primitive not in gap_primitives
            ]
            if missing_gaps:
                details = ", ".join(
                    f"{adapter} requires {primitive!r}"
                    for adapter, primitive in missing_gaps
                )
                raise ScaffoldSpecError(
                    "blocked unsupported adapters must appear exactly in "
                    f"readiness.library_gaps: {details}"
                )
            if not blockers:
                raise ScaffoldSpecError(
                    "readiness.status is 'blocked' but no blocking condition is recorded"
                )


@dataclass(frozen=True)
class ScaffoldReceipt:
    root: Path
    package_path: Path
    spec_path: Path | None
    slug: str
    item_count: int
    spec_sha256: str
    package_manifest_sha256: str
    runnable_manifest_sha256: str
    tree_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "package_path": str(self.package_path),
            "spec_path": str(self.spec_path) if self.spec_path else None,
            "slug": self.slug,
            "item_count": self.item_count,
            "spec_sha256": self.spec_sha256,
            "package_manifest_sha256": self.package_manifest_sha256,
            "runnable_manifest_sha256": self.runnable_manifest_sha256,
            "tree_sha256": self.tree_sha256,
        }


@dataclass(frozen=True)
class CompatibilityIssue:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class CompatibilityReport:
    root: Path
    compatible: bool
    issues: tuple[CompatibilityIssue, ...]
    benchmark_name: str | None = None
    item_count: int | None = None
    claim_boundary: str = STRUCTURAL_CLAIM_BOUNDARY

    @property
    def ok(self) -> bool:
        return self.compatible


def scaffold_benchmark(
    spec_or_path: BenchmarkScaffoldSpec | str | Path,
    *,
    output_root: str | Path,
) -> ScaffoldReceipt:
    """Create ``output_root/<slug>`` atomically from a ready sidecar."""

    spec = (
        spec_or_path
        if isinstance(spec_or_path, BenchmarkScaffoldSpec)
        else BenchmarkScaffoldSpec.from_json(spec_or_path)
    )
    if spec.readiness.status != "ready":
        gaps = ", ".join(gap.primitive for gap in spec.readiness.library_gaps)
        detail = f"; library gaps: {gaps}" if gaps else ""
        raise ScaffoldLibraryGapError(
            f"build spec readiness is {spec.readiness.status!r}; refusing partial scaffold{detail}"
        )
    if not spec.scorer.auto_bindable:
        raise ScaffoldLibraryGapError(
            f"scorer {spec.scorer.primitive!r} has no deterministic adapter "
            f"for {spec.schema_version!r}"
        )

    spec_digest = _verify_spec_source(spec)
    source_path = spec.source_path
    if source_path is None or spec.source.sha256 is None:
        raise ScaffoldError("ready build spec has no materialized source path and hash")
    source_bytes = _read_verified_file(source_path, spec.source.sha256, "source")
    artifact_paths: list[tuple[ArtifactSpec, Path]] = []
    for artifact in spec.artifacts:
        path = spec.artifact_path(artifact)
        if path is None or artifact.sha256 is None:
            raise ScaffoldError(f"artifact {artifact.role!r} has no path and hash")
        _read_verified_file(path, artifact.sha256, f"artifact {artifact.role!r}")
        artifact_paths.append((artifact, path))
    if spec.source.system_prompt is not None:
        actual_prompt_hash = hashlib.sha256(
            spec.source.system_prompt.text.encode("utf-8")
        ).hexdigest()
        if actual_prompt_hash != spec.source.system_prompt.sha256:
            raise ScaffoldError(
                "source.system_prompt SHA-256 does not match its exact UTF-8 text"
            )

    cohort_bundles: list[dict[str, Any]] | None = None
    attachment_assets: dict[str, bytes] | None = None
    attachments_manifest: dict[str, Any] | None = None
    if spec.schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION:
        items, cohort_bundles = _load_agentic_fhir_jsonl(
            spec,
            source_path,
            source_bytes,
        )
    elif spec.schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION:
        items = _load_multimodal_jsonl(spec, source_path, source_bytes)
        attachment_assets = _read_multimodal_assets(spec)
        attachments_manifest = {
            "schema_version": IMAGE_ATTACHMENTS_SCHEMA_VERSION,
            "assets": [
                asset.to_dict()
                for asset in (spec.multimodal.assets if spec.multimodal else ())
            ],
            "case_bindings": {
                item.id: list(item.attachments) for item in items
            },
        }
    else:
        items = _load_items(spec, source_path, source_bytes)
    _validate_items(
        items,
        scorer=spec.scorer,
        allowed_tools=(spec.agentic.allowed_tools if spec.agentic else None),
        allow_attachments=(
            spec.schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION
        ),
    )

    output = Path(output_root).expanduser()
    if output.is_symlink():
        raise ScaffoldError(f"output root cannot be a symlink: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if not output.is_dir():
        raise ScaffoldError(f"output root is not a directory: {output}")
    destination = output / spec.benchmark.slug
    if os.path.lexists(destination):
        raise ScaffoldError(f"benchmark destination already exists: {destination}")

    stage = Path(tempfile.mkdtemp(prefix=f".{spec.benchmark.slug}.staging-", dir=output))
    try:
        _materialize(
            stage,
            spec=spec,
            spec_digest=spec_digest,
            items=items,
            cohort_bundles=cohort_bundles,
            attachment_assets=attachment_assets,
            attachments_manifest=attachments_manifest,
            source_path=source_path,
            artifact_paths=artifact_paths,
        )
        staged = _inspect_benchmark(
            stage,
            expected_spec=spec,
            enforce_directory_name=False,
            verify_linked_provenance=True,
        )
        if not staged.compatible:
            raise ScaffoldError(
                "generated scaffold failed verification: "
                + "; ".join(issue.message for issue in staged.issues)
            )
        if os.path.lexists(destination):
            raise ScaffoldError(f"benchmark destination already exists: {destination}")
        os.rename(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)

    report = check_benchmark(destination)
    if not report.compatible:
        raise ScaffoldError(
            "materialized scaffold failed verification: "
            + "; ".join(issue.message for issue in report.issues)
        )
    manifest_path = destination / "package" / ASSET_MANIFEST_FILENAME
    runnable_manifest_path = destination / RUNNABLE_MANIFEST_FILENAME
    return ScaffoldReceipt(
        root=destination,
        package_path=destination / "package",
        spec_path=spec._source_path,
        slug=spec.benchmark.slug,
        item_count=len(items),
        spec_sha256=spec_digest,
        package_manifest_sha256=_file_sha256(manifest_path),
        runnable_manifest_sha256=_file_sha256(runnable_manifest_path),
        tree_sha256=_tree_sha256(destination),
    )


def check_benchmark(
    path: str | Path,
    *,
    verify_linked_provenance: bool = False,
) -> CompatibilityReport:
    """Offline structural check of package bytes and generated factory metadata.

    External source and planning artifacts are not runtime dependencies.
    ``verify_linked_provenance=True`` additionally re-hashes those linked files
    when they remain available in the authoring workspace.
    """

    return _inspect_benchmark(
        Path(path).expanduser(),
        expected_spec=None,
        enforce_directory_name=True,
        verify_linked_provenance=verify_linked_provenance,
    )


def load_scaffolded_benchmark(path: str | Path) -> Benchmark:
    """Safely load a generated scaffold without importing ``build.py``.

    The package is strict-verified, the generated factory bytes are checked
    against the digest bound inside ``benchmark.json``, and runtime settings
    are reconstructed from validated manifest provenance.
    """

    root = Path(path).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ScaffoldError(f"scaffolded benchmark root is unsafe or missing: {root}")
    package_path = root / "package"
    if package_path.is_symlink() or not package_path.is_dir():
        raise ScaffoldError(f"scaffolded package root is unsafe or missing: {package_path}")
    try:
        runnable_manifest = load_runnable_manifest(root / RUNNABLE_MANIFEST_FILENAME)
        verify_runnable_assets(root, runnable_manifest)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ScaffoldError(f"runnable benchmark contract is invalid: {exc}") from exc
    package = load_package(package_path, verify_assets=True)
    raw_manifest = _strict_json_load(root / "package" / "benchmark.json")
    _validate_raw_manifest(raw_manifest, package.manifest)
    _validate_raw_cases(
        package_path / "cases.jsonl",
        package.items,
        allow_attachments=(package.manifest.modality == "multimodal"),
    )
    if package.manifest.mast_compatible is not True:
        raise ScaffoldError("scaffolded package is not MAST-compatible")
    if runnable_manifest.benchmark_id != package.manifest.id:
        raise ScaffoldError("runnable benchmark id does not match package manifest")
    if runnable_manifest.benchmark_version != package.manifest.version:
        raise ScaffoldError("runnable benchmark version does not match package manifest")
    provenance = package.manifest.provenance
    schema_version = _provenance_schema_version(provenance)
    expected_modality = _expected_modality(schema_version)
    if package.manifest.modality != expected_modality:
        raise ScaffoldLibraryGapError(
            f"scaffolded package modality must be {expected_modality!r}, "
            f"got {package.manifest.modality!r}"
        )
    agentic = _agentic_spec_from_provenance(provenance, schema_version)
    scorer = _scorer_spec_from_manifest(
        package.manifest.scorer,
        schema_version=schema_version,
    )
    _validate_items(
        package.items,
        scorer=scorer,
        allowed_tools=(agentic.allowed_tools if agentic else None),
        allow_attachments=(
            schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION
        ),
    )
    if package.manifest.modality == "multimodal":
        multimodal_image_binding_from_package(package)
    expected_build_hash = provenance.get("generated_build_sha256")
    if not isinstance(expected_build_hash, str) or not _SHA256_RE.fullmatch(
        expected_build_hash
    ):
        raise ScaffoldError("manifest provenance.generated_build_sha256 is invalid")
    runner_record = _object(provenance.get("runner"), "manifest provenance.runner")
    runner = RunnerBuildSpec.from_dict(runner_record)
    source_record = _object(provenance.get("source"), "manifest provenance.source")
    prompt_record = source_record.get("system_prompt")
    prompt: str | None = None
    if prompt_record is not None:
        normalized_prompt = SystemPromptSpec.from_dict(
            _object(prompt_record, "manifest provenance.source.system_prompt")
        )
        actual = hashlib.sha256(normalized_prompt.text.encode("utf-8")).hexdigest()
        if actual != normalized_prompt.sha256:
            raise ScaffoldError("manifest system prompt text does not match its SHA-256")
        prompt = normalized_prompt.text
    canonical_build = _render_runtime_build(prompt, runner).encode("utf-8")
    canonical_build_hash = hashlib.sha256(canonical_build).hexdigest()
    if expected_build_hash != canonical_build_hash:
        raise ScaffoldError(
            "manifest generated_build_sha256 does not match the canonical runtime factory"
        )
    build_path = root / "build.py"
    build_bytes = _read_verified_file(
        build_path, expected_build_hash, "generated build.py"
    )
    if build_bytes != canonical_build:
        raise ScaffoldError("generated build.py is not the canonical runtime factory")
    validation_issues: list[CompatibilityIssue] = []
    _check_portable_provenance(provenance, validation_issues)
    _check_linked_provenance(
        provenance,
        root,
        validation_issues,
        verify_files=False,
        spec=None,
    )
    _check_nonpublic_controls(root, provenance, validation_issues)
    if validation_issues:
        raise ScaffoldError(
            "scaffold provenance is invalid: "
            + "; ".join(issue.message for issue in validation_issues)
        )
    return Benchmark.from_package(
        package,
        system_prompt=prompt,
        runner_config=runner.as_runner_config(),
    )


def _materialize(
    root: Path,
    *,
    spec: BenchmarkScaffoldSpec,
    spec_digest: str,
    items: Sequence[BenchmarkItem],
    cohort_bundles: Sequence[dict[str, Any]] | None,
    attachment_assets: Mapping[str, bytes] | None,
    attachments_manifest: dict[str, Any] | None,
    source_path: Path,
    artifact_paths: Sequence[tuple[ArtifactSpec, Path]],
) -> None:
    prompt = spec.source.system_prompt
    authorization = spec.data_governance.materialization_authorization
    build_bytes = _render_build(spec).encode("utf-8")
    provenance: dict[str, Any] = {
        "build_spec": {
            "schema_version": spec.schema_version,
            "path": (
                _relative_reference(root, spec._source_path)
                if spec._source_path
                else None
            ),
            "sha256": spec_digest,
        },
        "source": {
            "kind": spec.source.kind,
            "path": spec.source.path,
            "sha256": spec.source.sha256,
            "field_map": spec.source.field_map.to_dict(),
            "system_prompt": prompt.to_dict() if prompt else None,
        },
        "artifacts": [
            {
                "role": artifact.role,
                "path": artifact.path,
                "sha256": artifact.sha256,
            }
            for artifact, path in artifact_paths
        ],
        "benchmark": {
            "description": spec.benchmark.description,
            "mast_category": spec.benchmark.mast_category,
        },
        "runner": spec.runner.to_dict(),
        "smoke_test": spec.smoke_test.to_dict(),
        "first_sweep": [entry.to_dict() for entry in spec.first_sweep],
        "readiness": spec.readiness.to_dict(),
        "execution_allowlist_scope": EXECUTION_ALLOWLIST_SCOPE,
        "data_governance": {
            "classification": spec.data_governance.classification,
            "release_posture": spec.data_governance.release_posture,
            "materialization_authorization": {
                "authorized": authorization.authorized,
                "actor": authorization.actor,
                "confirmed_at": authorization.confirmed_at,
                "text_sha256": (
                    hashlib.sha256(authorization.text.encode("utf-8")).hexdigest()
                    if authorization.text is not None
                    else None
                ),
            },
        },
        "generated_build_sha256": hashlib.sha256(build_bytes).hexdigest(),
    }
    environment: dict[str, Any] | None = None
    if spec.agentic is not None:
        provenance["agentic"] = spec.agentic.to_dict()
        schemas = _fhir_tool_schema_map()
        environment = {
            "schema_version": AGENTIC_FHIR_ENV_SCHEMA_VERSION,
            "environment": spec.agentic.environment.to_dict(),
            "tool_catalog": spec.agentic.tool_catalog,
            "allowed_tools": list(spec.agentic.allowed_tools),
            "max_turns": spec.agentic.max_turns,
            "case_bindings": {
                item.id: f"cohort/{item.id}.fhir.json" for item in items
            },
            "tools": [schemas[name] for name in spec.agentic.allowed_tools],
        }
    if spec.multimodal is not None:
        provenance["multimodal"] = spec.multimodal.to_dict()
    manifest = BenchmarkManifest(
        id=spec.benchmark.slug,
        name=spec.benchmark.name,
        version=spec.benchmark.version,
        modality=spec.benchmark.modality,
        scorer=spec.scorer.manifest_dict(),
        mast_compatible=spec.benchmark.mast_compatible,
        provenance=provenance,
    )
    write_package(
        root / "package",
        manifest=manifest,
        items=items,
        env=environment,
        cohort_bundles=cohort_bundles,
        attachment_assets=attachment_assets,
        attachments=attachments_manifest,
        write_asset_manifest=True,
    )
    (root / "build.py").write_bytes(build_bytes)
    (root / "README.md").write_text(
        _render_readme(
            root,
            spec,
            spec_digest,
            source_path,
            artifact_paths,
        ),
        encoding="utf-8",
        newline="",
    )
    if spec.data_governance.release_posture != "public":
        (root / ".gitignore").write_text(
            "package/cases.jsonl\n",
            encoding="utf-8",
            newline="",
        )
    runnable_manifest = build_manifest_for_directory(
        root,
        benchmark_id=spec.benchmark.slug,
        benchmark_version=spec.benchmark.version,
        origin="builder",
        entry_point="build.py:build",
        dataset_path="package/cases.jsonl",
        scorer=manifest.scorer,
        source_revision=f"build-spec:{spec_digest}",
        build_spec_sha256=spec_digest,
        smoke_model=spec.smoke_test.model,
        smoke_limit=spec.smoke_test.limit,
        smoke_trials=spec.smoke_test.trials,
    )
    write_runnable_manifest(root / RUNNABLE_MANIFEST_FILENAME, runnable_manifest)


def _render_build(spec: BenchmarkScaffoldSpec) -> str:
    prompt = spec.source.system_prompt.text if spec.source.system_prompt else None
    return _render_runtime_build(prompt, spec.runner)


def _render_runtime_build(
    prompt: str | None,
    runner: RunnerBuildSpec,
) -> str:
    runner_lines = [
        f"        {name}={getattr(runner, name)!r}," for name in _RUNNER_FIELDS
    ]
    return "\n".join(
        [
            '"""Generated ARISEKit benchmark factory."""',
            "",
            "from pathlib import Path",
            "",
            "from arisekit.benchmark import Benchmark",
            "from arisekit.package import load_package",
            "from arisekit.runner import RunnerConfig",
            "",
            "",
            "HERE = Path(__file__).parent",
            "",
            "",
            "def build() -> Benchmark:",
            '    package = load_package(HERE / "package", verify_assets=True)',
            "    return Benchmark.from_package(",
            "        package,",
            f"        system_prompt={prompt!r},",
            "        runner_config=RunnerConfig(",
            *runner_lines,
            "        ),",
            "    )",
            "",
        ]
    )


def _render_readme(
    root: Path,
    spec: BenchmarkScaffoldSpec,
    spec_digest: str,
    source_path: Path,
    artifacts: Sequence[tuple[ArtifactSpec, Path]],
) -> str:
    nonpublic = spec.data_governance.release_posture != "public"
    run_parts = [
        "arisekit",
        "eval",
        spec.benchmark.slug,
        "--model",
        spec.smoke_test.model,
        "--limit",
        str(spec.smoke_test.limit),
        "--trials",
        str(spec.smoke_test.trials),
    ]
    if nonpublic:
        run_parts.extend(
            ["--provider-authorization", "provider-disclosure.json"]
        )
    run_command = shlex.join(run_parts)
    lines = [
        f"# {spec.benchmark.name}",
        "",
        spec.benchmark.description,
        "",
        f"- Benchmark id: `{spec.benchmark.slug}`",
        f"- Version: `{spec.benchmark.version}`",
        f"- MAST category: `{spec.benchmark.mast_category}`",
        f"- Dataset source: {_markdown_link(root, source_path, source_path.name)} "
        f"(SHA-256: `{spec.source.sha256}`)",
        f"- Scorer: `{spec.scorer.primitive}`",
    ]
    if spec.agentic is not None:
        lines.extend(
            [
                f"- Environment: `{spec.agentic.environment.primitive}` "
                "(FHIR R4, isolated per item and trial)",
                f"- Tool catalog: `{spec.agentic.tool_catalog}`",
                "- Allowed tools: "
                + ", ".join(f"`{name}`" for name in spec.agentic.allowed_tools),
                f"- Maximum agent turns: `{spec.agentic.max_turns}`",
            ]
        )
    if spec._source_path is not None:
        lines.append(
            f"- Build specification: {_markdown_link(root, spec._source_path, spec._source_path.name)} "
            f"(SHA-256: `{spec_digest}`)"
        )
    lines.extend(["", "## Planning artifacts", ""])
    lines.extend(
        f"- {artifact.role}: {_markdown_link(root, path, path.name)} "
        f"(SHA-256: `{artifact.sha256}`)"
        for artifact, path in artifacts
    )
    if nonpublic:
        bundle_hash = _file_sha256(
            root / "package" / ASSET_MANIFEST_FILENAME
        )
        lines.extend(
            [
                "",
                "## Data handling warning",
                "",
                f"This benchmark is `{spec.data_governance.classification}` with a "
                f"`{spec.data_governance.release_posture}` release posture. The "
                "generated `package/cases.jsonl` is ignored by Git and must not be "
                "committed without a new, explicit release decision.",
                "",
                "## Provider disclosure authorization",
                "",
                "Every model run for this non-public generated package requires an "
                "external `ProviderDisclosureAuthorization` before dispatch.",
                "",
                f"- `generated_bundle_hash`: `{bundle_hash}`",
                f"- `access_classification`: "
                f"`{spec.data_governance.release_posture}`",
                "- `judge_providers`: `[]`",
                "- Solver-provider map:",
                *[
                    f"  - `{entry.model}` -> `{entry.provider}`"
                    for entry in spec.first_sweep
                ],
                "",
                "The bundle hash is the SHA-256 of the exact "
                "`package/asset-manifest.json` bytes. Keep the authorization "
                "record outside this package.",
            ]
        )
    lines.extend(
        [
            "",
            "## Planned smoke test",
            "",
            f"- Model: `{spec.smoke_test.model}`",
            f"- Limit: `{spec.smoke_test.limit}`",
            f"- Trials: `{spec.smoke_test.trials}`",
            "",
            "## Run",
            "",
            f"`{run_command}`",
            "",
            "The allowed model routes in the build specification are the reviewed "
            "execution allowlist from compliance planning. They are not a "
            "`ProviderDisclosureAuthorization`.",
            "",
            STRUCTURAL_CLAIM_BOUNDARY,
            "",
        ]
    )
    return "\n".join(lines)


def _inspect_benchmark(
    root: Path,
    *,
    expected_spec: BenchmarkScaffoldSpec | None,
    enforce_directory_name: bool,
    verify_linked_provenance: bool,
) -> CompatibilityReport:
    issues: list[CompatibilityIssue] = []
    if root.is_symlink():
        return _failed(root, "unsafe-root", "benchmark root cannot be a symlink")
    if not root.is_dir():
        return _failed(root, "missing-root", "benchmark root is not a directory")
    readme_path = root / "README.md"
    build_path = root / "build.py"
    package_path = root / "package"
    if not readme_path.is_file():
        issues.append(CompatibilityIssue("missing-readme", "README.md is missing", str(readme_path)))
    if not build_path.is_file():
        issues.append(CompatibilityIssue("missing-build", "build.py is missing", str(build_path)))
    if package_path.is_symlink() or not package_path.is_dir():
        issues.append(
            CompatibilityIssue(
                "unsafe-package-root",
                "package must be a regular directory, not a symlink",
                str(package_path),
            )
        )
        return CompatibilityReport(root, False, tuple(issues))

    try:
        package = load_package(package_path, verify_assets=True)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            CompatibilityIssue(
                "package-integrity",
                f"strict package verification failed: {exc}",
                str(package_path),
            )
        )
        return CompatibilityReport(root, False, tuple(issues))

    try:
        raw_manifest = _strict_json_load(package_path / "benchmark.json")
        _validate_raw_manifest(raw_manifest, package.manifest)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            CompatibilityIssue(
                "invalid-manifest",
                f"package benchmark.json is invalid: {exc}",
                str(package_path / "benchmark.json"),
            )
        )
    try:
        _validate_raw_cases(
            package_path / "cases.jsonl",
            package.items,
            allow_attachments=(package.manifest.modality == "multimodal"),
        )
    except Exception as exc:  # noqa: BLE001
        issues.append(
            CompatibilityIssue(
                "invalid-items",
                f"package cases.jsonl is invalid: {exc}",
                str(package_path / "cases.jsonl"),
            )
        )
    if package.manifest.mast_compatible is not True:
        issues.append(
            CompatibilityIssue(
                "mast-incompatible",
                "scaffolded package is not MAST-compatible",
                str(package_path / "benchmark.json"),
            )
        )

    if enforce_directory_name and root.name != package.manifest.id:
        issues.append(
            CompatibilityIssue(
                "name-mismatch",
                f"directory name {root.name!r} does not match benchmark id {package.manifest.id!r}",
                str(root),
            )
        )
    provenance = package.manifest.provenance
    try:
        schema_version = _provenance_schema_version(provenance)
        agentic = _agentic_spec_from_provenance(provenance, schema_version)
        package_scorer = _scorer_spec_from_manifest(
            package.manifest.scorer,
            schema_version=schema_version,
        )
        _validate_items(
            package.items,
            scorer=package_scorer,
            allowed_tools=(agentic.allowed_tools if agentic else None),
            allow_attachments=(
                schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION
            ),
        )
    except ScaffoldError as exc:
        issues.append(
            CompatibilityIssue("invalid-items", str(exc), str(package_path / "cases.jsonl"))
        )
        schema_version = BUILD_SPEC_SCHEMA_VERSION
    expected_modality = _expected_modality(schema_version)
    if package.manifest.modality != expected_modality:
        issues.append(
            CompatibilityIssue(
                "unsupported-modality",
                f"scaffolded package modality must be {expected_modality!r}, "
                f"got {package.manifest.modality!r}",
                str(package_path / "benchmark.json"),
            )
        )
    if package.manifest.modality == "agentic-fhir":
        try:
            agentic_fhir_binding_from_package(package)
        except (OSError, UnicodeError, ValueError) as exc:
            issues.append(
                CompatibilityIssue(
                    "invalid-agentic-environment",
                    f"agentic FHIR package binding is invalid: {exc}",
                    str(package_path / "env.json"),
                )
            )
    if package.manifest.modality == "multimodal":
        try:
            multimodal_image_binding_from_package(package)
        except (OSError, UnicodeError, ValueError) as exc:
            issues.append(
                CompatibilityIssue(
                    "invalid-multimodal-attachments",
                    f"multimodal package binding is invalid: {exc}",
                    str(package_path / "attachments.json"),
                )
            )

    _check_portable_provenance(provenance, issues)
    _check_runnable_contract(root, package, issues)
    spec = expected_spec
    build_spec_record = provenance.get("build_spec")
    if not isinstance(build_spec_record, dict):
        issues.append(CompatibilityIssue("missing-provenance", "manifest provenance.build_spec is missing"))
    else:
        if set(build_spec_record) != {"schema_version", "path", "sha256"}:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "build-spec provenance fields are invalid",
                )
            )
        if build_spec_record.get("schema_version") not in SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "build-spec provenance schema version is invalid",
                )
            )
        spec_hash = build_spec_record.get("sha256")
        spec_path_raw = build_spec_record.get("path")
        if not isinstance(spec_hash, str) or not _SHA256_RE.fullmatch(spec_hash):
            issues.append(CompatibilityIssue("invalid-provenance", "build-spec digest is invalid"))
        if spec_path_raw is not None and not isinstance(spec_path_raw, str):
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "manifest provenance.build_spec.path must be relative or null",
                )
            )
        elif isinstance(spec_path_raw, str):
            try:
                _validate_link_reference(
                    spec_path_raw, "manifest provenance.build_spec.path"
                )
            except ScaffoldError as exc:
                issues.append(CompatibilityIssue("invalid-provenance", str(exc)))
        if (
            verify_linked_provenance
            and spec is None
            and isinstance(spec_path_raw, str)
        ):
            try:
                linked_spec = _resolve_provenance_reference(root, spec_path_raw)
            except ScaffoldError:
                linked_spec = root / "__invalid_provenance_path__"
            if not linked_spec.is_file():
                issues.append(
                    CompatibilityIssue("stale-provenance", "linked build spec is missing", str(linked_spec))
                )
            elif isinstance(spec_hash, str) and _file_sha256(linked_spec) != spec_hash:
                issues.append(
                    CompatibilityIssue("stale-provenance", "linked build spec hash changed", str(linked_spec))
                )
            else:
                try:
                    spec = BenchmarkScaffoldSpec.from_json(linked_spec)
                except Exception as exc:  # noqa: BLE001
                    issues.append(
                        CompatibilityIssue("invalid-spec", f"linked build spec is invalid: {exc}", str(linked_spec))
                    )

    _check_linked_provenance(
        provenance,
        root,
        issues,
        verify_files=verify_linked_provenance,
        spec=spec,
    )

    if spec is not None:
        try:
            _compare_manifest_to_spec(package, spec, issues)
        except (OSError, ScaffoldError) as exc:
            issues.append(
                CompatibilityIssue(
                    "stale-provenance",
                    f"could not compare linked build spec provenance: {exc}",
                )
            )
    benchmark: Benchmark | None = None
    if build_path.is_file():
        try:
            benchmark = load_scaffolded_benchmark(root)
        except Exception as exc:  # noqa: BLE001
            issues.append(
                CompatibilityIssue(
                    "safe-load-failed",
                    f"safe scaffold load failed: {exc}",
                    str(build_path),
                )
            )
    if benchmark is not None:
        if benchmark.name != package.manifest.id:
            issues.append(
                CompatibilityIssue(
                    "name-mismatch",
                    f"build() returned {benchmark.name!r}; expected {package.manifest.id!r}",
                    str(build_path),
                )
            )
        if [item.id for item in benchmark.dataset] != [item.id for item in package.items]:
            issues.append(
                CompatibilityIssue(
                    "dataset-mismatch",
                    "build() dataset does not preserve packaged item order and ids",
                    str(build_path),
                )
            )
        _verify_csv_contract(benchmark, issues)
    _check_nonpublic_controls(root, provenance, issues)
    return CompatibilityReport(
        root=root,
        compatible=not issues,
        issues=tuple(issues),
        benchmark_name=package.manifest.id,
        item_count=len(package.items),
    )


def _check_runnable_contract(
    root: Path,
    package: BenchmarkPackage,
    issues: list[CompatibilityIssue],
) -> None:
    path = root / RUNNABLE_MANIFEST_FILENAME
    if path.is_symlink() or not path.is_file():
        issues.append(
            CompatibilityIssue(
                "missing-runnable-manifest",
                f"{RUNNABLE_MANIFEST_FILENAME} is missing or unsafe",
                str(path),
            )
        )
        return
    try:
        manifest = load_runnable_manifest(path)
        verify_runnable_assets(root, manifest)
    except (OSError, UnicodeError, ValueError) as exc:
        issues.append(
            CompatibilityIssue(
                "invalid-runnable-manifest",
                f"runnable benchmark contract is invalid: {exc}",
                str(path),
            )
        )
        return

    expected = {
        "benchmark_id": package.manifest.id,
        "benchmark_version": package.manifest.version,
        "origin": "builder",
        "entry_point": "build.py:build",
        "entry_point_sha256": _file_sha256(root / "build.py"),
        "dataset_sha256": _file_sha256(root / "package" / "cases.jsonl"),
        "scorer_sha256": hashlib.sha256(
            json.dumps(
                package.manifest.scorer,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    for name, value in expected.items():
        if getattr(manifest, name) != value:
            issues.append(
                CompatibilityIssue(
                    "runnable-manifest-mismatch",
                    f"runnable manifest {name} does not match materialized bytes",
                    str(path),
                )
            )
    build_spec = package.manifest.provenance.get("build_spec")
    if isinstance(build_spec, Mapping):
        expected_hash = build_spec.get("sha256")
        if manifest.build_spec_sha256 != expected_hash:
            issues.append(
                CompatibilityIssue(
                    "runnable-manifest-mismatch",
                    "runnable manifest build_spec_sha256 does not match package provenance",
                    str(path),
                )
            )
        if manifest.source_revision != f"build-spec:{expected_hash}":
            issues.append(
                CompatibilityIssue(
                    "runnable-manifest-mismatch",
                    "runnable manifest source_revision does not match build provenance",
                    str(path),
                )
            )


def _check_portable_provenance(
    provenance: Mapping[str, Any],
    issues: list[CompatibilityIssue],
) -> None:
    schema_version: str | None = None
    build_spec_record = provenance.get("build_spec")
    if isinstance(build_spec_record, Mapping):
        raw_version = build_spec_record.get("schema_version")
        if isinstance(raw_version, str):
            schema_version = raw_version
    expected_fields = set(_PROVENANCE_FIELDS)
    if schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION:
        expected_fields.add("agentic")
    if schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION:
        expected_fields.add("multimodal")
    if set(provenance) != expected_fields:
        issues.append(
            CompatibilityIssue(
                "invalid-provenance",
                "manifest provenance top-level fields are invalid",
            )
        )

    build_spec = provenance.get("build_spec")
    if not isinstance(build_spec, dict) or set(build_spec) != {
        "schema_version",
        "path",
        "sha256",
    }:
        issues.append(
            CompatibilityIssue(
                "invalid-provenance", "build-spec provenance fields are invalid"
            )
        )
    else:
        if build_spec.get("schema_version") not in SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "build-spec provenance schema version is invalid",
                )
            )
        digest = build_spec.get("sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance", "build-spec provenance digest is invalid"
                )
            )
        reference = build_spec.get("path")
        if reference is not None:
            try:
                _validate_link_reference(
                    reference, "manifest provenance.build_spec.path"
                )
            except (ScaffoldError, TypeError) as exc:
                issues.append(CompatibilityIssue("invalid-provenance", str(exc)))

    if schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION:
        try:
            AgenticFHIRSpec.from_dict(
                _object(provenance.get("agentic"), "manifest provenance.agentic")
            )
        except ScaffoldError as exc:
            issues.append(CompatibilityIssue("invalid-provenance", str(exc)))
    if schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION:
        try:
            multimodal = MultimodalImageSpec.from_dict(
                _object(
                    provenance.get("multimodal"),
                    "manifest provenance.multimodal",
                )
            )
            if not multimodal.assets:
                raise ScaffoldError(
                    "manifest provenance.multimodal.assets must not be empty"
                )
        except ScaffoldError as exc:
            issues.append(CompatibilityIssue("invalid-provenance", str(exc)))

    benchmark = provenance.get("benchmark")
    if not isinstance(benchmark, dict) or set(benchmark) != {
        "description",
        "mast_category",
    }:
        issues.append(
            CompatibilityIssue(
                "invalid-provenance", "benchmark provenance fields are invalid"
            )
        )
    else:
        for field_name in ("description", "mast_category"):
            value = benchmark.get(field_name)
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    CompatibilityIssue(
                        "invalid-provenance",
                        f"benchmark provenance {field_name} is invalid",
                    )
                )

    try:
        RunnerBuildSpec.from_dict(
            _object(provenance.get("runner"), "manifest provenance.runner")
        )
    except ScaffoldError as exc:
        issues.append(CompatibilityIssue("invalid-provenance", str(exc)))

    smoke: SmokeTestSpec | None = None
    try:
        smoke = SmokeTestSpec.from_dict(
            _object(provenance.get("smoke_test"), "manifest provenance.smoke_test")
        )
    except ScaffoldError as exc:
        issues.append(CompatibilityIssue("invalid-provenance", str(exc)))

    sweep: tuple[SweepModelSpec, ...] = ()
    raw_sweep = provenance.get("first_sweep")
    if not isinstance(raw_sweep, list) or not raw_sweep:
        issues.append(
            CompatibilityIssue(
                "invalid-provenance",
                "manifest provenance.first_sweep must be a non-empty list",
            )
        )
    else:
        parsed: list[SweepModelSpec] = []
        try:
            parsed = [
                SweepModelSpec.from_dict(
                    _object(value, f"manifest provenance.first_sweep[{index}]"),
                    index,
                )
                for index, value in enumerate(raw_sweep)
            ]
        except ScaffoldError as exc:
            issues.append(CompatibilityIssue("invalid-provenance", str(exc)))
        sweep = tuple(parsed)
        models = [entry.model for entry in sweep]
        if len(models) != len(set(models)):
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "manifest provenance.first_sweep contains duplicate model routes",
                )
            )

    readiness: ReadinessSpec | None = None
    try:
        readiness = ReadinessSpec.from_dict(
            _object(provenance.get("readiness"), "manifest provenance.readiness")
        )
    except ScaffoldError as exc:
        issues.append(CompatibilityIssue("invalid-provenance", str(exc)))
    if readiness is not None:
        if readiness.status != "ready":
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance", "scaffold readiness status must be ready"
                )
            )
        if readiness.data_profile != "materialized":
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "scaffold readiness data profile must be materialized",
                )
            )
        if not readiness.allowed_model_routes:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance", "allowed_model_routes must not be empty"
                )
            )
        if readiness.library_gaps or readiness.open_questions:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "ready scaffold cannot retain library gaps or open questions",
                )
            )
        confirmation = readiness.user_confirmation
        if confirmation is None or not _is_rfc3339(confirmation.confirmed_at):
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "readiness confirmation is missing or not RFC 3339",
                )
            )
        planned_models = {entry.model for entry in sweep}
        if smoke is not None:
            planned_models.add(smoke.model)
        disallowed = sorted(planned_models - set(readiness.allowed_model_routes))
        if disallowed:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "planned models are outside allowed_model_routes: "
                    + ", ".join(disallowed),
                )
            )
        missing_sweep = sorted(
            set(readiness.allowed_model_routes)
            - {entry.model for entry in sweep}
        )
        if missing_sweep:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    "allowed_model_routes are missing from first_sweep: "
                    + ", ".join(missing_sweep),
                )
            )

    if provenance.get("execution_allowlist_scope") != EXECUTION_ALLOWLIST_SCOPE:
        issues.append(
            CompatibilityIssue(
                "invalid-provenance", "execution allowlist scope is invalid"
            )
        )
    build_hash = provenance.get("generated_build_sha256")
    if not isinstance(build_hash, str) or not _SHA256_RE.fullmatch(build_hash):
        issues.append(
            CompatibilityIssue(
                "invalid-provenance", "generated build digest is invalid"
            )
            )


def _provenance_schema_version(provenance: Mapping[str, Any]) -> str:
    build_spec = _object(
        provenance.get("build_spec"),
        "manifest provenance.build_spec",
    )
    schema_version = _text(
        build_spec.get("schema_version"),
        "manifest provenance.build_spec.schema_version",
    )
    if schema_version not in SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS:
        raise ScaffoldError(
            f"unsupported scaffold build-spec schema {schema_version!r}"
        )
    return schema_version


def _agentic_spec_from_provenance(
    provenance: Mapping[str, Any],
    schema_version: str,
) -> AgenticFHIRSpec | None:
    if schema_version != AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION:
        if "agentic" in provenance:
            raise ScaffoldError(
                "only build-spec v2 provenance can contain agentic configuration"
            )
        return None
    return AgenticFHIRSpec.from_dict(
        _object(provenance.get("agentic"), "manifest provenance.agentic")
    )


def _multimodal_spec_from_provenance(
    provenance: Mapping[str, Any],
    schema_version: str,
) -> MultimodalImageSpec | None:
    if schema_version != MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION:
        if "multimodal" in provenance:
            raise ScaffoldError(
                "only build-spec v3 provenance can contain multimodal configuration"
            )
        return None
    return MultimodalImageSpec.from_dict(
        _object(provenance.get("multimodal"), "manifest provenance.multimodal")
    )


def _check_linked_provenance(
    provenance: Mapping[str, Any],
    root: Path,
    issues: list[CompatibilityIssue],
    *,
    verify_files: bool,
    spec: BenchmarkScaffoldSpec | None,
) -> None:
    try:
        schema_version = _provenance_schema_version(provenance)
    except ScaffoldError:
        schema_version = BUILD_SPEC_SCHEMA_VERSION
    is_agentic_v2 = schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION
    is_multimodal_v3 = schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION
    source = provenance.get("source")
    if not isinstance(source, dict):
        issues.append(CompatibilityIssue("missing-provenance", "manifest provenance.source is missing"))
    else:
        if set(source) != {"kind", "path", "sha256", "field_map", "system_prompt"}:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance", "source provenance fields are invalid"
                )
            )
        supported_source_kinds = (
            ("jsonl",)
            if is_agentic_v2 or is_multimodal_v3
            else ("jsonl", "csv")
        )
        if source.get("kind") not in supported_source_kinds:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance", "source provenance kind is unsupported"
                )
            )
        try:
            field_map = FieldMapSpec.from_dict(
                _object(source.get("field_map"), "manifest provenance.source.field_map"),
                include_fhir_bundle=is_agentic_v2,
            )
            if (
                field_map.id is None
                or field_map.prompt is None
                or field_map.ground_truth is None
            ):
                raise ScaffoldError(
                    "scaffolded source provenance has an incomplete field map"
                )
            if is_multimodal_v3 and field_map.attachments != "attachments":
                raise ScaffoldError(
                    "scaffolded multimodal source provenance must bind attachments"
                )
            if not is_multimodal_v3 and field_map.attachments is not None:
                raise ScaffoldError(
                    "scaffolded source provenance cannot contain an attachment mapping"
                )
            if is_agentic_v2 and field_map.fhir_bundle != "fhir_bundle":
                raise ScaffoldError(
                    "scaffolded agentic source provenance must bind fhir_bundle"
                )
        except ScaffoldError as exc:
            issues.append(CompatibilityIssue("invalid-provenance", str(exc)))
        _check_linked_hash(
            source,
            "source",
            issues,
            verify_file=verify_files,
            authoring_root=spec._base_dir if spec is not None else None,
        )
        if is_multimodal_v3:
            try:
                multimodal = _multimodal_spec_from_provenance(
                    provenance, schema_version
                )
                if multimodal is None:
                    raise ScaffoldError(
                        "scaffolded multimodal provenance is missing"
                    )
                if verify_files and spec is not None:
                    _read_multimodal_assets(spec)
            except ScaffoldError as exc:
                issues.append(CompatibilityIssue("stale-provenance", str(exc)))
    artifacts = provenance.get("artifacts")
    if not isinstance(artifacts, list):
        issues.append(CompatibilityIssue("missing-provenance", "manifest provenance.artifacts is missing"))
        return
    roles: list[str] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            issues.append(CompatibilityIssue("invalid-provenance", f"artifact provenance entry {index} is invalid"))
            continue
        if set(artifact) != {"role", "path", "sha256"}:
            issues.append(
                CompatibilityIssue(
                    "invalid-provenance",
                    f"artifact provenance entry {index} fields are invalid",
                )
            )
        role = artifact.get("role")
        if isinstance(role, str):
            roles.append(role)
        _check_linked_hash(
            artifact,
            f"artifact {role!r}",
            issues,
            verify_file=verify_files,
            authoring_root=spec._base_dir if spec is not None else None,
        )
    if set(roles) != set(_ARTIFACT_ROLES) or len(roles) != len(set(roles)):
        issues.append(
            CompatibilityIssue(
                "invalid-provenance",
                "artifact provenance does not contain each required planning role exactly once",
            )
        )


def _check_linked_hash(
    record: Mapping[str, Any],
    label: str,
    issues: list[CompatibilityIssue],
    *,
    verify_file: bool,
    authoring_root: Path | None,
) -> None:
    raw_path = record.get("path")
    expected = record.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
        issues.append(CompatibilityIssue("invalid-provenance", f"{label} path or SHA-256 is invalid"))
        return
    try:
        _validate_relative_reference(raw_path, f"manifest provenance {label} path")
    except ScaffoldError as exc:
        issues.append(CompatibilityIssue("invalid-provenance", str(exc)))
        return
    if not verify_file:
        return
    if authoring_root is None:
        issues.append(
            CompatibilityIssue(
                "stale-provenance",
                f"cannot verify linked {label} without a validated build sidecar",
            )
        )
        return
    try:
        path = _resolve_optional_path(raw_path, authoring_root)
        assert path is not None
        _read_verified_file(path, expected, f"linked {label}")
    except ScaffoldError as exc:
        issues.append(CompatibilityIssue("stale-provenance", str(exc)))


def _compare_manifest_to_spec(
    package: BenchmarkPackage,
    spec: BenchmarkScaffoldSpec,
    issues: list[CompatibilityIssue],
) -> None:
    expected = {
        "id": spec.benchmark.slug,
        "name": spec.benchmark.name,
        "version": spec.benchmark.version,
        "modality": spec.benchmark.modality,
        "scorer": spec.scorer.manifest_dict(),
        "mast_compatible": spec.benchmark.mast_compatible,
    }
    for name, value in expected.items():
        actual = getattr(package.manifest, name)
        if actual != value:
            issues.append(
                CompatibilityIssue(
                    "manifest-mismatch",
                    f"package manifest {name} {actual!r} does not match build spec {value!r}",
                    str(package.root / "benchmark.json"),
                )
            )
    authorization = spec.data_governance.materialization_authorization
    spec_digest = (
        _file_sha256(spec._source_path)
        if spec._source_path is not None
        else hashlib.sha256(_canonical_json_bytes(spec.to_dict())).hexdigest()
    )
    expected_provenance = {
        "build_spec": {
            "schema_version": spec.schema_version,
            "path": (
                _relative_reference(package.root.parent, spec._source_path)
                if spec._source_path is not None
                else None
            ),
            "sha256": spec_digest,
        },
        "source": {
            "kind": spec.source.kind,
            "path": spec.source.path,
            "sha256": spec.source.sha256,
            "field_map": spec.source.field_map.to_dict(),
            "system_prompt": (
                spec.source.system_prompt.to_dict()
                if spec.source.system_prompt is not None
                else None
            ),
        },
        "artifacts": [artifact.to_dict() for artifact in spec.artifacts],
        "benchmark": {
            "description": spec.benchmark.description,
            "mast_category": spec.benchmark.mast_category,
        },
        "runner": spec.runner.to_dict(),
        "smoke_test": spec.smoke_test.to_dict(),
        "first_sweep": [entry.to_dict() for entry in spec.first_sweep],
        "readiness": spec.readiness.to_dict(),
        "execution_allowlist_scope": EXECUTION_ALLOWLIST_SCOPE,
        "data_governance": {
            "classification": spec.data_governance.classification,
            "release_posture": spec.data_governance.release_posture,
            "materialization_authorization": {
                "authorized": authorization.authorized,
                "actor": authorization.actor,
                "confirmed_at": authorization.confirmed_at,
                "text_sha256": (
                    hashlib.sha256(authorization.text.encode("utf-8")).hexdigest()
                    if authorization.text is not None
                    else None
                ),
            },
        },
        "generated_build_sha256": hashlib.sha256(
            _render_build(spec).encode("utf-8")
        ).hexdigest(),
    }
    if spec.agentic is not None:
        expected_provenance["agentic"] = spec.agentic.to_dict()
    if spec.multimodal is not None:
        expected_provenance["multimodal"] = spec.multimodal.to_dict()
    if package.manifest.provenance != expected_provenance:
        issues.append(
            CompatibilityIssue(
                "manifest-mismatch",
                "package provenance does not exactly match the validated build spec",
                str(package.root / "benchmark.json"),
            )
        )


def _scorer_spec_from_manifest(
    data: Mapping[str, Any],
    *,
    schema_version: str = BUILD_SPEC_SCHEMA_VERSION,
) -> ScorerSpec:
    if not isinstance(data, Mapping):
        raise ScaffoldError("package scorer manifest must be an object")
    kind = data.get("kind")
    if kind == "rubric-judge":
        primitive = "arisekit.judges.rubric.RubricJudge"
    elif isinstance(kind, str) and kind in _SCORER_PRIMITIVES:
        primitive = _SCORER_PRIMITIVES[kind]
    elif (
        kind == "pass-at-one"
        and schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION
    ):
        primitive = _AGENTIC_SCORER_PRIMITIVE
    else:
        raise ScaffoldLibraryGapError(
            f"package scorer kind {kind!r} has no adapter for {schema_version!r}"
        )
    return ScorerSpec.from_dict(
        {
            "kind": kind,
            "primitive": primitive,
            "options": {key: value for key, value in data.items() if key != "kind"},
        }
    )


def _verify_csv_contract(
    benchmark: Benchmark,
    issues: list[CompatibilityIssue],
) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="arisekit-scaffold-check-") as raw:
            directory = Path(raw)
            result = Results(
                benchmark=benchmark.name,
                model="offline-structural-check",
                raw=[],
                per_item=[],
                metrics=[Metric("structural", 1.0, n=1)],
                summary=RunSummary(0, 0, 0, 0.0, directory / "raw.jsonl"),
            )
            csv_path = result.to_csv(directory / "scores.csv")
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
        if not rows or tuple(rows[0]) != _RESULTS_CSV_HEADER:
            issues.append(
                CompatibilityIssue(
                    "csv-shape",
                    "Results.to_csv does not emit the required MAST-compatible header",
                )
            )
        elif len(rows) != 2 or len(rows[1]) != len(_RESULTS_CSV_HEADER):
            issues.append(
                CompatibilityIssue(
                    "csv-shape",
                    "Results.to_csv does not emit the required seven-column metric row",
                )
            )
    except Exception as exc:  # noqa: BLE001
        issues.append(
            CompatibilityIssue(
                "csv-shape",
                f"could not verify Results.to_csv output shape: {exc}",
            )
        )


def _check_nonpublic_controls(
    root: Path,
    provenance: Mapping[str, Any],
    issues: list[CompatibilityIssue],
) -> None:
    try:
        schema_version = _provenance_schema_version(provenance)
    except ScaffoldError:
        schema_version = BUILD_SPEC_SCHEMA_VERSION
    governance = provenance.get("data_governance")
    if not isinstance(governance, dict):
        issues.append(
            CompatibilityIssue(
                "missing-governance",
                "manifest provenance.data_governance is missing",
            )
        )
        return
    if set(governance) != {
        "classification",
        "release_posture",
        "materialization_authorization",
    }:
        issues.append(
            CompatibilityIssue(
                "invalid-governance",
                "data-governance provenance fields are invalid",
            )
        )
    classification = governance.get("classification")
    release_posture = governance.get("release_posture")
    if classification not in _DATA_CLASSIFICATIONS:
        issues.append(
            CompatibilityIssue(
                "invalid-governance",
                f"unknown data classification {classification!r}",
            )
        )
    if release_posture not in _RELEASE_POSTURES:
        issues.append(
            CompatibilityIssue(
                "invalid-governance",
                f"unknown release posture {release_posture!r}",
            )
        )
    if release_posture in _RELEASE_POSTURES:
        _check_root_topology(root, release_posture, issues)
    if classification in ("limited", "identifiable"):
        issues.append(
            CompatibilityIssue(
                "unsafe-governance",
                f"build-spec v1 cannot materialize {classification!r} data",
            )
        )
    if release_posture == "public" and classification not in ("public", "synthetic"):
        issues.append(
            CompatibilityIssue(
                "unsafe-governance",
                "public release posture requires public or synthetic data",
            )
        )
    if schema_version == AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION and (
        classification not in ("public", "synthetic")
        or release_posture != "public"
    ):
        issues.append(
            CompatibilityIssue(
                "unsafe-governance",
                "build-spec v2 agentic-fhir currently requires public or "
                "synthetic data with a public release posture",
            )
        )
    if schema_version == MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION and (
        classification not in ("public", "synthetic")
        or release_posture != "public"
    ):
        issues.append(
            CompatibilityIssue(
                "unsafe-governance",
                "build-spec v3 multimodal currently requires public or "
                "synthetic data with a public release posture",
            )
        )

    authorization = governance.get("materialization_authorization")
    if not isinstance(authorization, dict):
        issues.append(
            CompatibilityIssue(
                "missing-governance",
                "materialization-authorization provenance is missing",
            )
        )
    else:
        if set(authorization) != {
            "authorized",
            "actor",
            "confirmed_at",
            "text_sha256",
        }:
            issues.append(
                CompatibilityIssue(
                    "invalid-governance",
                    "materialization-authorization provenance fields are invalid",
                )
            )
        if authorization.get("authorized") is not True:
            issues.append(
                CompatibilityIssue(
                    "invalid-governance",
                    "materialization authorization is not affirmative",
                )
            )
        for field_name in ("actor", "confirmed_at"):
            value = authorization.get(field_name)
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    CompatibilityIssue(
                        "invalid-governance",
                        f"materialization authorization {field_name} is invalid",
                    )
                )
        confirmed_at = authorization.get("confirmed_at")
        if isinstance(confirmed_at, str) and not _is_rfc3339(confirmed_at):
            issues.append(
                CompatibilityIssue(
                    "invalid-governance",
                    "materialization authorization confirmed_at is not RFC 3339",
                )
            )
        text_digest = authorization.get("text_sha256")
        if not isinstance(text_digest, str) or not _SHA256_RE.fullmatch(text_digest):
            issues.append(
                CompatibilityIssue(
                    "invalid-governance",
                    "materialization authorization text digest is invalid",
                )
            )

    if release_posture == "public":
        return
    ignore_path = root / ".gitignore"
    if ignore_path.is_symlink() or not ignore_path.is_file():
        issues.append(
            CompatibilityIssue(
                "missing-data-control",
                "non-public scaffold must include a regular .gitignore",
                str(ignore_path),
            )
        )
    else:
        try:
            ignore_text = ignore_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append(
                CompatibilityIssue(
                    "invalid-data-control",
                    f"cannot read non-public .gitignore: {exc}",
                    str(ignore_path),
                )
            )
        else:
            if ignore_text != "package/cases.jsonl\n":
                issues.append(
                    CompatibilityIssue(
                        "invalid-data-control",
                        "non-public .gitignore must be exactly package/cases.jsonl",
                        str(ignore_path),
                    )
                )
    readme_path = root / "README.md"
    if readme_path.is_symlink():
        return
    try:
        readme = readme_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return
    if "must not be committed without a new, explicit release decision" not in readme:
        issues.append(
            CompatibilityIssue(
                "missing-data-control",
                "non-public README data-handling warning is missing",
                str(readme_path),
            )
        )


def _check_root_topology(
    root: Path,
    release_posture: str,
    issues: list[CompatibilityIssue],
) -> None:
    expected = {
        "README.md",
        "build.py",
        RUNNABLE_MANIFEST_FILENAME,
        "package",
    }
    if release_posture != "public":
        expected.add(".gitignore")
    try:
        entries = {entry.name: entry for entry in root.iterdir()}
    except OSError as exc:
        issues.append(
            CompatibilityIssue(
                "invalid-root-topology",
                f"cannot inspect scaffold root: {exc}",
                str(root),
            )
        )
        return
    if set(entries) != expected:
        issues.append(
            CompatibilityIssue(
                "invalid-root-topology",
                "scaffold root entries differ; "
                f"missing={sorted(expected - set(entries))}, "
                f"extra={sorted(set(entries) - expected)}",
                str(root),
            )
        )
    for name in ("README.md", "build.py", RUNNABLE_MANIFEST_FILENAME):
        path = entries.get(name)
        if path is None:
            continue
        if path.is_symlink() or not path.is_file():
            issues.append(
                CompatibilityIssue(
                    "invalid-root-topology",
                    f"{name} must be a regular non-symlink file",
                    str(path),
                )
            )
    package_path = entries.get("package")
    if package_path is not None and (
        package_path.is_symlink() or not package_path.is_dir()
    ):
        issues.append(
            CompatibilityIssue(
                "invalid-root-topology",
                "package must be a regular non-symlink directory",
                str(package_path),
            )
        )


def _load_items(
    spec: BenchmarkScaffoldSpec,
    path: Path,
    source_bytes: bytes,
) -> list[BenchmarkItem]:
    if spec.source.kind == "jsonl":
        return _load_jsonl(spec.source.field_map, path, source_bytes)
    return _load_csv(spec.source.field_map, path, source_bytes)


def _load_agentic_fhir_jsonl(
    spec: BenchmarkScaffoldSpec,
    path: Path,
    source_bytes: bytes,
) -> tuple[list[BenchmarkItem], list[dict[str, Any]]]:
    """Normalize v2 rows while keeping embedded FHIR data out of cases.jsonl."""

    field_map = spec.source.field_map
    bundle_field = field_map.fhir_bundle
    if bundle_field is None:
        raise ScaffoldError("ready agentic-fhir source has no FHIR bundle mapping")
    if spec.agentic is None:
        raise ScaffoldError("ready agentic-fhir source has no agentic configuration")
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScaffoldError(f"{path} is not UTF-8: {exc}") from exc

    items: list[BenchmarkItem] = []
    bundles: list[dict[str, Any]] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        context = f"{path}:{line_number}"
        try:
            row = strict_json_loads(raw, context, error=ScaffoldSpecError)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ScaffoldError(str(exc)) from exc
        if not isinstance(row, dict):
            raise ScaffoldError(f"{context} must contain a top-level object")
        if bundle_field not in row:
            raise ScaffoldError(
                f"{context} is missing mapped FHIR bundle field {bundle_field!r}"
            )
        item = _map_row(row, field_map, context, csv_mode=False)
        bundle = _validate_fhir_bundle(row[bundle_field], item.id, context)
        _validate_agentic_pass_condition(
            item.ground_truth,
            item_id=item.id,
            allowed_tools=spec.agentic.allowed_tools,
        )
        items.append(item)
        bundles.append(bundle)
    return items, bundles


def _load_multimodal_jsonl(
    spec: BenchmarkScaffoldSpec,
    path: Path,
    source_bytes: bytes,
) -> list[BenchmarkItem]:
    """Normalize v3 rows and bind every ordered image reference."""

    if spec.multimodal is None:
        raise ScaffoldError("ready multimodal source has no attachment inventory")
    items = _load_jsonl(spec.source.field_map, path, source_bytes)
    declared = {asset.path for asset in spec.multimodal.assets}
    referenced: set[str] = set()
    for item in items:
        if not item.attachments:
            raise ScaffoldError(
                f"item {item.id!r} must reference at least one image attachment"
            )
        if len(item.attachments) > _MAX_ATTACHMENTS_PER_ITEM:
            raise ScaffoldError(
                f"item {item.id!r} exceeds the {_MAX_ATTACHMENTS_PER_ITEM}-image limit"
            )
        if len(item.attachments) != len(set(item.attachments)):
            raise ScaffoldError(
                f"item {item.id!r} contains duplicate attachment references"
            )
        for attachment in item.attachments:
            if not _ATTACHMENT_PATH_RE.fullmatch(attachment):
                raise ScaffoldError(
                    f"item {item.id!r} attachment {attachment!r} must be a flat "
                    "PNG or JPEG path under attachments/"
                )
            if attachment not in declared:
                raise ScaffoldError(
                    f"item {item.id!r} references uninventoried attachment "
                    f"{attachment!r}"
                )
            referenced.add(attachment)
    unused = sorted(declared - referenced)
    if unused:
        raise ScaffoldError(
            "multimodal inventory contains unreferenced assets: " + ", ".join(unused)
        )
    return items


def _read_multimodal_assets(
    spec: BenchmarkScaffoldSpec,
) -> dict[str, bytes]:
    if spec.multimodal is None:
        raise ScaffoldError("multimodal attachment inventory is missing")
    assets: dict[str, bytes] = {}
    for asset in spec.multimodal.assets:
        path = spec.attachment_path(asset)
        _reject_authoring_symlink_chain(spec._base_dir, path, asset.path)
        payload = _read_verified_file(
            path,
            asset.sha256,
            f"multimodal attachment {asset.path!r}",
        )
        if len(payload) != asset.size_bytes:
            raise ScaffoldError(
                f"multimodal attachment size mismatch for {asset.path}: "
                f"{len(payload)} != {asset.size_bytes}"
            )
        _validate_image_magic(payload, asset.media_type, asset.path)
        assets[asset.path] = payload
    return assets


def _reject_authoring_symlink_chain(
    root: Path,
    path: Path,
    label: str,
) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ScaffoldError(f"attachment path escapes authoring root: {label}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ScaffoldError(f"attachment path uses a symlink: {label}")


def _validate_image_magic(payload: bytes, media_type: str, label: str) -> None:
    if media_type == "image/png":
        valid = payload.startswith(b"\x89PNG\r\n\x1a\n")
    elif media_type == "image/jpeg":
        valid = payload.startswith(b"\xff\xd8\xff") and payload.endswith(
            b"\xff\xd9"
        )
    else:
        valid = False
    if not valid:
        raise ScaffoldError(
            f"multimodal attachment {label!r} bytes do not match {media_type}"
        )


def _validate_fhir_bundle(
    value: Any,
    item_id: str,
    context: str,
) -> dict[str, Any]:
    if not _FHIR_ID_RE.fullmatch(item_id):
        raise ScaffoldError(
            f"{context} item id must be a valid FHIR id for cohort binding"
        )
    if not isinstance(value, Mapping):
        raise ScaffoldError(f"{context}.fhir_bundle must be a FHIR Bundle object")
    bundle = _canonical_json(value, f"{context}.fhir_bundle")
    if bundle.get("resourceType") != "Bundle":
        raise ScaffoldError(
            f"{context}.fhir_bundle resourceType must be 'Bundle'"
        )
    if bundle.get("id") != item_id:
        raise ScaffoldError(
            f"{context}.fhir_bundle id must exactly match item id {item_id!r}"
        )
    if not isinstance(bundle.get("type"), str) or not bundle["type"].strip():
        raise ScaffoldError(f"{context}.fhir_bundle type must be non-empty text")
    entries = bundle.get("entry", [])
    if not isinstance(entries, list):
        raise ScaffoldError(f"{context}.fhir_bundle entry must be a list")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
            raise ScaffoldError(
                f"{context}.fhir_bundle.entry[{index}] must contain a resource object"
            )
        resource = entry["resource"]
        if not isinstance(resource.get("resourceType"), str) or not resource[
            "resourceType"
        ].strip():
            raise ScaffoldError(
                f"{context}.fhir_bundle.entry[{index}].resource needs resourceType"
            )
    return bundle


def _validate_agentic_pass_condition(
    value: Any,
    *,
    item_id: str,
    allowed_tools: Sequence[str],
) -> None:
    context = f"item {item_id!r} pass condition"
    if not isinstance(value, Mapping):
        raise ScaffoldError(f"{context} must be an object")
    _exact_fields(
        value,
        {"schema_version", "required_tool_calls", "final_response_contains"},
        context,
    )
    if value["schema_version"] != AGENTIC_PASS_CONDITION_SCHEMA_VERSION:
        raise ScaffoldError(
            f"{context} schema_version must be "
            f"{AGENTIC_PASS_CONDITION_SCHEMA_VERSION!r}"
        )
    calls = _list(value["required_tool_calls"], f"{context}.required_tool_calls")
    if not calls:
        raise ScaffoldError(f"{context}.required_tool_calls must not be empty")
    call_keys: set[str] = set()
    for index, raw_call in enumerate(calls):
        call_context = f"{context}.required_tool_calls[{index}]"
        call = _object(raw_call, call_context)
        _exact_fields(call, {"name", "arguments"}, call_context)
        name = _single_line_text(call["name"], f"{call_context}.name")
        if name not in allowed_tools:
            raise ScaffoldError(
                f"{call_context}.name {name!r} is not in agentic.allowed_tools"
            )
        arguments = _object(call["arguments"], f"{call_context}.arguments")
        _validate_fhir_tool_arguments(name, arguments, call_context)
        key = json.dumps(
            {"name": name, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if key in call_keys:
            raise ScaffoldError(f"{context}.required_tool_calls contains duplicates")
        call_keys.add(key)

    terms = _list(
        value["final_response_contains"],
        f"{context}.final_response_contains",
    )
    if not terms or any(not isinstance(term, str) or not term.strip() for term in terms):
        raise ScaffoldError(
            f"{context}.final_response_contains must contain non-empty strings"
        )
    normalized_terms = [term.casefold() for term in terms]
    if len(normalized_terms) != len(set(normalized_terms)):
        raise ScaffoldError(
            f"{context}.final_response_contains contains duplicates"
        )


def _validate_fhir_tool_arguments(
    name: str,
    arguments: Mapping[str, Any],
    context: str,
) -> None:
    parameters = _fhir_tool_schema_map()[name]["parameters"]
    properties = parameters.get("properties", {})
    required = set(parameters.get("required", []))
    missing = sorted(required - set(arguments))
    unknown = sorted(set(arguments) - set(properties))
    if missing or unknown:
        raise ScaffoldError(
            f"{context}.arguments fields differ; missing={missing}, unknown={unknown}"
        )
    for argument, value in arguments.items():
        schema = properties[argument]
        if schema.get("type") == "string" and not isinstance(value, str):
            raise ScaffoldError(
                f"{context}.arguments.{argument} must be a string"
            )
        enum = schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ScaffoldError(
                f"{context}.arguments.{argument} must be one of {enum!r}"
            )


def _load_jsonl(
    field_map: FieldMapSpec,
    path: Path,
    source_bytes: bytes,
) -> list[BenchmarkItem]:
    items: list[BenchmarkItem] = []
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScaffoldError(f"{path} is not UTF-8: {exc}") from exc
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = strict_json_loads(raw, f"{path}:{line_number}", error=ScaffoldSpecError)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ScaffoldError(str(exc)) from exc
        if not isinstance(row, dict):
            raise ScaffoldError(f"{path}:{line_number} must contain a top-level object")
        items.append(_map_row(row, field_map, f"{path}:{line_number}", csv_mode=False))
    return items


def _load_csv(
    field_map: FieldMapSpec,
    path: Path,
    source_bytes: bytes,
) -> list[BenchmarkItem]:
    items: list[BenchmarkItem] = []
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScaffoldError(f"{path} is not UTF-8: {exc}") from exc
    with io.StringIO(text, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ScaffoldError(f"{path} has no CSV header")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ScaffoldError(f"{path} has duplicate CSV column names")
        required = _mapped_source_fields(field_map)
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ScaffoldError(f"{path} is missing mapped CSV columns: {', '.join(missing)}")
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(row.get(header) is None for header in reader.fieldnames):
                raise ScaffoldError(
                    f"{path}:{row_number} CSV row width does not match its header"
                )
            items.append(_map_row(row, field_map, f"{path}:{row_number}", csv_mode=True))
    return items


def _map_row(
    row: Mapping[str, Any],
    field_map: FieldMapSpec,
    context: str,
    *,
    csv_mode: bool,
) -> BenchmarkItem:
    required_names = (field_map.id, field_map.prompt, field_map.ground_truth)
    if any(name is None for name in required_names):
        raise ScaffoldError("ready source field map is incomplete")
    missing = sorted(name for name in _mapped_source_fields(field_map) if name not in row)
    if missing:
        raise ScaffoldError(f"{context} is missing mapped fields: {', '.join(missing)}")
    item_id = row[field_map.id or ""]
    prompt = row[field_map.prompt or ""]
    ground_truth = row[field_map.ground_truth or ""]
    if csv_mode and ground_truth == "":
        ground_truth = None
    metadata = {
        output_key: row[source_key]
        for output_key, source_key in field_map.metadata.items()
    }
    attachments = (
        row[field_map.attachments]
        if field_map.attachments is not None
        else []
    )
    if csv_mode and field_map.attachments is not None:
        raise ScaffoldError("CSV attachment mappings are not supported")
    return _make_item(
        item_id=item_id,
        prompt=prompt,
        ground_truth=ground_truth,
        metadata=metadata,
        attachments=attachments,
        context=context,
    )


def _make_item(
    *,
    item_id: Any,
    prompt: Any,
    ground_truth: Any,
    metadata: Any,
    attachments: Any,
    context: str,
) -> BenchmarkItem:
    if not isinstance(item_id, str) or not item_id.strip():
        raise ScaffoldError(f"{context} has an empty or non-string item id")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ScaffoldError(f"{context} prompt must be a non-empty string")
    if ground_truth is None:
        raise ScaffoldError(f"{context} is missing ground truth required by deterministic scoring")
    if not isinstance(metadata, dict):
        raise ScaffoldError(f"{context} metadata must be an object")
    if not isinstance(attachments, list) or any(not isinstance(value, str) for value in attachments):
        raise ScaffoldError(f"{context} attachments must be a list of strings")
    return BenchmarkItem(
        id=item_id.strip(),
        prompt=_canonical_json(prompt, f"{context}.prompt"),
        metadata=_canonical_json(metadata, f"{context}.metadata"),
        ground_truth=_canonical_json(ground_truth, f"{context}.ground_truth"),
        attachments=list(attachments),
    )


def _validate_items(
    items: Sequence[BenchmarkItem],
    *,
    scorer: ScorerSpec,
    allowed_tools: Sequence[str] | None = None,
    allow_attachments: bool = False,
) -> None:
    if not items:
        raise ScaffoldError("dataset contains no benchmark items")
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item.id, str) or not item.id.strip():
            raise ScaffoldError(f"item {index} has an empty or non-string id")
        if item.id in seen:
            raise ScaffoldError(f"dataset contains duplicate item id {item.id!r}")
        seen.add(item.id)
        if item.ground_truth is None:
            raise ScaffoldError(
                f"item {item.id!r} is missing ground truth required by deterministic scoring"
            )
        if not isinstance(item.prompt, str) or not item.prompt.strip():
            raise ScaffoldError(
                f"item {item.id!r} prompt must be a non-empty string"
            )
        if not isinstance(item.metadata, dict):
            raise ScaffoldError(f"item {item.id!r} metadata must be an object")
        if item.attachments and not allow_attachments:
            raise ScaffoldError(
                f"item {item.id!r} has attachments, but this scaffold adapter "
                "does not copy or hash attachment assets"
            )
        if allow_attachments:
            if not item.attachments:
                raise ScaffoldError(
                    f"item {item.id!r} must contain at least one attachment"
                )
            if len(item.attachments) > _MAX_ATTACHMENTS_PER_ITEM:
                raise ScaffoldError(
                    f"item {item.id!r} exceeds the attachment-count limit"
                )
            if len(item.attachments) != len(set(item.attachments)):
                raise ScaffoldError(
                    f"item {item.id!r} contains duplicate attachments"
                )
            if any(
                not _ATTACHMENT_PATH_RE.fullmatch(path)
                for path in item.attachments
            ):
                raise ScaffoldError(
                    f"item {item.id!r} contains an unsafe or unsupported attachment"
                )
        _validate_ground_truth(item, scorer)
        if scorer.kind == "pass-at-one":
            if allowed_tools is None:
                raise ScaffoldError(
                    "agentic pass-at-one items require a bound tool allowlist"
                )
            _validate_agentic_pass_condition(
                item.ground_truth,
                item_id=item.id,
                allowed_tools=allowed_tools,
            )
        try:
            json.dumps(item.to_dict(), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ScaffoldError(f"item {item.id!r} is not JSON-serializable: {exc}") from exc


def _validate_ground_truth(item: BenchmarkItem, scorer: ScorerSpec) -> None:
    ground_truth = item.ground_truth
    if scorer.kind == "numeric":
        if isinstance(ground_truth, bool):
            raise ScaffoldError(
                f"item {item.id!r} ground truth must be numeric for numeric scoring"
            )
        try:
            number = float(ground_truth)
        except (TypeError, ValueError) as exc:
            raise ScaffoldError(
                f"item {item.id!r} ground truth must be numeric for numeric scoring"
            ) from exc
        if not math.isfinite(number):
            raise ScaffoldError(
                f"item {item.id!r} ground truth must be finite for numeric scoring"
            )
        return
    if scorer.kind == "choice":
        choices = scorer.options.get("choices")
        if not isinstance(choices, list):
            raise ScaffoldError("choice scorer is missing its choices list")
        case_sensitive = bool(scorer.options.get("case_sensitive", False))
        expected = str(ground_truth)
        normalized_expected = expected if case_sensitive else expected.lower()
        normalized_choices = [
            choice if case_sensitive else choice.lower() for choice in choices
        ]
        if normalized_expected not in normalized_choices:
            raise ScaffoldError(
                f"item {item.id!r} ground truth {expected!r} is not in scorer choices"
            )
        return
    if scorer.kind == "contains":
        values = ground_truth if isinstance(ground_truth, list) else [ground_truth]
        if not values or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ScaffoldError(
                f"item {item.id!r} ground truth must contain one or more non-empty strings"
            )


def _validate_scorer_options(kind: str, options: Mapping[str, Any]) -> None:
    unknown = set(options) - set(_SCORER_OPTIONS[kind])
    if unknown:
        raise ScaffoldSpecError(
            f"scorer.options has unsupported keys for {kind!r}: {', '.join(sorted(unknown))}"
        )
    if kind == "choice" and "choices" not in options:
        raise ScaffoldSpecError("scorer.options.choices is required for choice scoring")
    for key, value in options.items():
        if key in ("case_sensitive", "strip") and not isinstance(value, bool):
            raise ScaffoldSpecError(f"scorer.options.{key} must be boolean")
        if key == "name":
            _text(value, "scorer.options.name")
        if key == "choices":
            values = _list(value, "scorer.options.choices")
            if not values or any(not isinstance(choice, str) or not choice for choice in values):
                raise ScaffoldSpecError("scorer.options.choices must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ScaffoldSpecError("scorer.options.choices contains duplicates")
        if key in ("atol", "rtol"):
            _finite_number(value, f"scorer.options.{key}", minimum=0.0)


def _verify_spec_source(spec: BenchmarkScaffoldSpec) -> str:
    if spec._source_path is None:
        return hashlib.sha256(_canonical_json_bytes(spec.to_dict())).hexdigest()
    fresh = BenchmarkScaffoldSpec.from_json(spec._source_path)
    if fresh.to_dict() != spec.to_dict():
        raise ScaffoldError(f"build spec changed after it was loaded: {spec._source_path}")
    return _file_sha256(spec._source_path)


def _validate_raw_manifest(
    value: Any,
    manifest: BenchmarkManifest,
) -> None:
    if not isinstance(value, dict):
        raise ScaffoldError("manifest must be a JSON object")
    expected_fields = {
        "id",
        "name",
        "version",
        "modality",
        "scorer",
        "mast_compatible",
        "provenance",
    }
    if set(value) != expected_fields:
        raise ScaffoldError(
            "manifest fields differ; "
            f"missing={sorted(expected_fields - set(value))}, "
            f"unknown={sorted(set(value) - expected_fields)}"
        )
    for field_name in ("id", "name", "version", "modality"):
        field_value = value[field_name]
        if not isinstance(field_value, str) or not field_value.strip():
            raise ScaffoldError(f"manifest {field_name} must be a non-empty string")
    _validate_slug(value["id"])
    if not _SEMVER_RE.fullmatch(value["version"]):
        raise ScaffoldError("manifest version must be semantic version text")
    if not isinstance(value["scorer"], dict) or not value["scorer"]:
        raise ScaffoldError("manifest scorer must be a non-empty object")
    if not isinstance(value["mast_compatible"], bool):
        raise ScaffoldError("manifest mast_compatible must be boolean")
    if not isinstance(value["provenance"], dict):
        raise ScaffoldError("manifest provenance must be an object")
    if value != manifest.to_dict():
        raise ScaffoldError("manifest values changed during package normalization")


def _validate_raw_cases(
    path: Path,
    items: Sequence[BenchmarkItem],
    *,
    allow_attachments: bool = False,
) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ScaffoldError(f"cannot read raw cases: {exc}") from exc
    records: list[dict[str, Any]] = []
    expected_fields = {
        "id",
        "prompt",
        "metadata",
        "ground_truth",
        "attachments",
    }
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = strict_json_loads(raw, f"{path}:{line_number}", error=ScaffoldSpecError)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ScaffoldError(str(exc)) from exc
        if not isinstance(value, dict):
            raise ScaffoldError(f"{path}:{line_number} must contain an object")
        if set(value) != expected_fields:
            raise ScaffoldError(
                f"{path}:{line_number} fields differ; "
                f"missing={sorted(expected_fields - set(value))}, "
                f"unknown={sorted(set(value) - expected_fields)}"
            )
        if not isinstance(value["id"], str) or not value["id"].strip():
            raise ScaffoldError(f"{path}:{line_number} id must be a non-empty string")
        if not isinstance(value["prompt"], str) or not value["prompt"].strip():
            raise ScaffoldError(
                f"{path}:{line_number} prompt must be a non-empty string"
            )
        if not isinstance(value["metadata"], dict):
            raise ScaffoldError(f"{path}:{line_number} metadata must be an object")
        if value["ground_truth"] is None:
            raise ScaffoldError(f"{path}:{line_number} ground_truth cannot be null")
        attachments = value["attachments"]
        if not isinstance(attachments, list) or any(
            not isinstance(entry, str) for entry in attachments
        ):
            raise ScaffoldError(
                f"{path}:{line_number} attachments must be a list of strings"
            )
        if attachments and not allow_attachments:
            raise ScaffoldError(
                f"{path}:{line_number} attachments must be empty for build-spec v1"
            )
        if allow_attachments and not attachments:
            raise ScaffoldError(
                f"{path}:{line_number} attachments must not be empty for build-spec v3"
            )
        if allow_attachments and (
            len(attachments) > _MAX_ATTACHMENTS_PER_ITEM
            or len(attachments) != len(set(attachments))
            or any(not _ATTACHMENT_PATH_RE.fullmatch(entry) for entry in attachments)
        ):
            raise ScaffoldError(
                f"{path}:{line_number} attachments violate the build-spec v3 image policy"
            )
        _canonical_json(value, f"{path}:{line_number}")
        records.append(value)
    if not records:
        raise ScaffoldError("package contains no raw benchmark cases")
    if records != [item.to_dict() for item in items]:
        raise ScaffoldError("case values changed during package normalization")


def _read_verified_file(path: Path, expected: str, label: str) -> bytes:
    if path.is_symlink():
        raise ScaffoldError(f"{label} cannot be a symlink: {path}")
    if not path.is_file():
        raise ScaffoldError(f"{label} is not a regular file: {path}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ScaffoldError(f"cannot read {label} {path}: {exc}") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ScaffoldError(f"{label} SHA-256 mismatch for {path}: {actual} != {expected}")
    return payload


def _mapped_source_fields(field_map: FieldMapSpec) -> set[str]:
    return {
        value
        for value in (
            field_map.id,
            field_map.prompt,
            field_map.ground_truth,
            field_map.attachments,
            field_map.fhir_bundle,
            *field_map.metadata.values(),
        )
        if value is not None
    }


def _fhir_tool_schema_map() -> dict[str, dict[str, Any]]:
    from arisekit.env.fhir import FHIREnvironment, fhir_tools

    return {
        tool.name: {
            "name": tool.name,
            "description": tool.description,
            "parameters": _canonical_json(
                tool.parameters,
                f"FHIR tool {tool.name!r} parameters",
            ),
        }
        for tool in fhir_tools(FHIREnvironment([]))
    }


def _strict_json_load(path: Path) -> Any:
    return strict_json_loads(path.read_text(encoding="utf-8"), str(path), error=ScaffoldSpecError)


def _canonical_json(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ScaffoldSpecError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, (list, tuple)):
        return [_canonical_json(entry, f"{path}[{index}]") for index, entry in enumerate(value)]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ScaffoldSpecError(f"{path} object keys must be strings")
        return {key: _canonical_json(value[key], f"{path}.{key}") for key in sorted(value)}
    raise ScaffoldSpecError(f"{path} contains non-JSON value of type {type(value).__name__}")


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _resolve_optional_path(value: str | None, base: Path) -> Path | None:
    if value is None:
        return None
    _validate_relative_reference(value, "build-spec path")
    base = base.resolve()
    candidate = base / PurePosixPath(value)
    current = base
    for component in PurePosixPath(value).parts:
        current = current / component
        if current.is_symlink():
            raise ScaffoldError(f"build-spec path cannot contain a symlink: {value}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ScaffoldError(f"build-spec path escapes its sidecar directory: {value}") from exc
    return resolved


def _relative_reference(root: Path, target: Path) -> str:
    reference = os.path.relpath(target.resolve(), start=root.resolve())
    normalized = Path(reference).as_posix()
    _validate_link_reference(normalized, "provenance path")
    return normalized


def _resolve_provenance_reference(root: Path, value: str) -> Path:
    _validate_link_reference(value, "manifest provenance path")
    return (root.resolve() / PurePosixPath(value)).resolve()


def _validate_relative_reference(value: str, name: str) -> None:
    _validate_link_reference(value, name)
    if ".." in PurePosixPath(value).parts:
        raise ScaffoldSpecError(f"{name} cannot contain parent traversal")


def _validate_link_reference(value: str, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ScaffoldSpecError(f"{name} must be a non-empty relative path")
    if any(ord(character) < 32 for character in value):
        raise ScaffoldSpecError(f"{name} contains control characters")
    if "\\" in value:
        raise ScaffoldSpecError(f"{name} must use '/' separators")
    path = PurePosixPath(value)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", value):
        raise ScaffoldSpecError(f"{name} must be relative")
    if value != path.as_posix() or value in (".", ".."):
        raise ScaffoldSpecError(f"{name} must be a normalized relative path")


def _markdown_link(root: Path, path: Path, label: str) -> str:
    target = _relative_reference(root, path).replace(">", "%3E")
    safe_label = label.replace("[", "\\[").replace("]", "\\]")
    return f"[{safe_label}](<{target}>)"


def _failed(root: Path, code: str, message: str) -> CompatibilityReport:
    return CompatibilityReport(
        root=root,
        compatible=False,
        issues=(CompatibilityIssue(code, message, str(root)),),
    )


def _object(value: Any, name: str) -> Mapping[str, Any]:
    return mapping(value, name, error=ScaffoldSpecError)


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ScaffoldSpecError(f"{name} must be a list")
    return value


def _exact_fields(data: Mapping[str, Any], fields: set[str], name: str) -> None:
    _object(data, name)
    missing = fields - set(data)
    unknown = set(data) - fields
    if missing or unknown:
        raise ScaffoldSpecError(
            f"{name} fields differ; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _text(value: Any, name: str) -> str:
    return text(value, name, error=ScaffoldSpecError)


def _single_line_text(value: Any, name: str) -> str:
    text = _text(value, name)
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ScaffoldSpecError(f"{name} cannot contain control characters")
    return text


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _sha256(value: Any, name: str) -> str:
    return sha256_hex(value, name, error=ScaffoldSpecError)


def _is_rfc3339(value: str) -> bool:
    if not _RFC3339_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.utcoffset() is not None


def _positive_int(value: Any, name: str) -> int:
    return positive_int(value, name, error=ScaffoldSpecError)


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)


def _finite_number(value: Any, name: str, *, minimum: float | None = None,
                   exclusive_minimum: float | None = None) -> float:
    return number(value, name, minimum=minimum, exclusive_minimum=exclusive_minimum, error=ScaffoldSpecError)


def _optional_finite_number(
    value: Any,
    name: str,
    *,
    exclusive_minimum: float | None = None,
) -> float | None:
    if value is None:
        return None
    return _finite_number(value, name, exclusive_minimum=exclusive_minimum)


def _validate_slug(value: str) -> None:
    if not _SLUG_RE.fullmatch(value):
        raise ScaffoldSpecError(
            "benchmark.slug must be 1-128 lowercase letters, digits, or hyphens "
            "and cannot contain path separators or traversal"
        )


def _duplicates(values: Sequence[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


__all__ = [
    "AGENTIC_FHIR_BUILD_SPEC_SCHEMA_VERSION",
    "AGENTIC_FHIR_ENV_SCHEMA_VERSION",
    "AGENTIC_PASS_CONDITION_SCHEMA_VERSION",
    "BUILD_SPEC_SCHEMA_VERSION",
    "FHIR_TOOL_CATALOG_VERSION",
    "IMAGE_ATTACHMENTS_SCHEMA_VERSION",
    "MULTIMODAL_BUILD_SPEC_SCHEMA_VERSION",
    "SUPPORTED_BUILD_SPEC_SCHEMA_VERSIONS",
    "AgenticEnvironmentSpec",
    "AgenticFHIRSpec",
    "BenchmarkScaffoldSpec",
    "CompatibilityIssue",
    "CompatibilityReport",
    "ScaffoldError",
    "ScaffoldLibraryGapError",
    "ScaffoldReceipt",
    "ScaffoldSpecError",
    "ImageAttachmentAssetSpec",
    "MultimodalImageSpec",
    "STRUCTURAL_CLAIM_BOUNDARY",
    "check_benchmark",
    "load_scaffolded_benchmark",
    "scaffold_benchmark",
]

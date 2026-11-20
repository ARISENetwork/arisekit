"""Tamper-evident real-versus-synthetic benchmark parity analysis.

The engine in this module is intentionally independent of any benchmark's
prompt, rubric, or judge implementation. It consumes scalar endpoint
observations after those benchmark-specific steps have completed.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from statistics import fmean
from typing import Any

from arisekit.archetype import (
    ArchetypeId,
    JudgePolicy,
    MarginUnit,
    ModelRoute,
    SyntheticBenchmarkProgram,
    VariantSelectionPolicy,
)
from arisekit.common.hashing import strict_canonical_sha256 as _digest
from arisekit.common.jsonio import strict_canonical_json as _canonical_json, strict_json_loads
from arisekit.common.records import StrictCanonicalRecord
from arisekit.common.stats import percentile_interval, quantile, spearman_rank_agreement
from arisekit.common.validate import enum_member, number, sha256_hex, text
from arisekit.authoring.content_inventory import ReferenceSelectionInventory
from arisekit.run_manifest import RunManifest
from arisekit.authoring.specialty import BenchmarkTrack
from arisekit.authoring.specialty_inventory import SpecialtyCellInventory

INPUT_SCHEMA_VERSION = "arisekit.synthetic-parity-input.v5"
RUN_ADAPTER_RECEIPT_SCHEMA_VERSION = (
    "arisekit.synthetic-parity-solver-run-adapter-receipt.v1"
)
RUN_EVIDENCE_SCHEMA_VERSION = "arisekit.synthetic-parity-solver-run-evidence.v2"
RULE_SCHEMA_VERSION = "arisekit.synthetic-parity-rule.v1"
REPORT_SCHEMA_VERSION = "arisekit.synthetic-parity-report.v4"
BOOTSTRAP_ALGORITHM = "paired-case-family-percentile-bootstrap-v1"
SOLVER_OBSERVATION_SUBSET_HASH_ALGORITHM = "canonical-endpoint-observation-subset-v1"
REPRESENTATIVE_VERDICT_SCOPE = "overall-primary-diagnostics-nonterminal"
STRESS_VERDICT_SCOPE = "diagnostic-only-no-terminal-verdict"
VERDICT_SCOPE = REPRESENTATIVE_VERDICT_SCOPE
ARTIFACT_HASH_KIND = "self-checksum-requires-external-byte-pin"
RUN_MANIFEST_ROUTE_SNAPSHOT_KEY = "arisekit_requested_snapshot"
RUN_MANIFEST_ROUTE_FAMILY_KEY = "arisekit_requested_family"
RUN_MANIFEST_RUNTIME_CONFIG_HASH_KEY = "arisekit_runtime_config_hash"
RUN_MANIFEST_ADAPTER_CODE_HASH_KEY = "arisekit_run_adapter_code_hash"
RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY = (
    "arisekit_expected_provider_model_identity"
)
RUN_MANIFEST_EVALUATION_CONTRACT_HASH_KEY = "arisekit_evaluation_contract_hash"
RUN_MANIFEST_SELECTION_PROTOCOL_HASH_KEY = "arisekit_selection_protocol_hash"
RUN_MANIFEST_SELECTION_HASH_KEY = "arisekit_selection_manifest_hash"


class ArmRole(str, Enum):
    """The two required benchmark roles."""

    REAL = "real"
    SYNTHETIC = "synthetic"


class SelectionBasis(str, Enum):
    """Permitted and explicitly prohibited selection bases."""

    PREREGISTERED = "preregistered"
    RANDOM = "random"
    SOURCE_METADATA = "source-metadata"
    EVALUATED_OUTCOMES = "evaluated-outcomes"


class ParityVerdict(str, Enum):
    """Terminal result derived from confidence intervals."""

    EQUIVALENT = "equivalent"
    NON_EQUIVALENT = "non-equivalent"
    INCONCLUSIVE = "inconclusive"


class VariantSlotKind(str, Enum):
    """Logical slot semantics before either arm is evaluated."""

    BASELINE = "baseline"
    PERTURBATION = "perturbation"
    VARIANT = "variant"


@dataclass(frozen=True)
class ModelIdentity:
    """One immutable model snapshot in the shared comparison panel."""

    model_id: str
    model_family: str

    def __post_init__(self) -> None:
        _text("model_id", self.model_id)
        _text("model_family", self.model_family)

    def to_dict(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "model_family": self.model_family,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelIdentity":
        _fields(data, {"model_id", "model_family"}, "model identity")
        return cls(model_id=data["model_id"], model_family=data["model_family"])


@dataclass(frozen=True)
class BenchmarkArm(StrictCanonicalRecord):
    """Hash-bound identity and evaluation contract for one benchmark arm."""

    role: ArmRole
    arm_id: str
    benchmark_id: str
    benchmark_version: str
    content_hash: str
    evaluation_contract_hash: str
    selection_protocol_hash: str
    selection_manifest_hash: str
    source_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _enum(ArmRole, self.role, "arm role"))
        for name in (
            "arm_id",
            "benchmark_id",
            "benchmark_version",
            "source_revision",
        ):
            _text(name, getattr(self, name))
        for name in (
            "content_hash",
            "evaluation_contract_hash",
            "selection_protocol_hash",
            "selection_manifest_hash",
        ):
            _hash(name, getattr(self, name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "arm_id": self.arm_id,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "content_hash": self.content_hash,
            "evaluation_contract_hash": self.evaluation_contract_hash,
            "selection_protocol_hash": self.selection_protocol_hash,
            "selection_manifest_hash": self.selection_manifest_hash,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkArm":
        _fields(
            data,
            {
                "role",
                "arm_id",
                "benchmark_id",
                "benchmark_version",
                "content_hash",
                "evaluation_contract_hash",
                "selection_protocol_hash",
                "selection_manifest_hash",
                "source_revision",
            },
            "benchmark arm",
        )
        return cls(
            role=data["role"],
            arm_id=data["arm_id"],
            benchmark_id=data["benchmark_id"],
            benchmark_version=data["benchmark_version"],
            content_hash=data["content_hash"],
            evaluation_contract_hash=data["evaluation_contract_hash"],
            selection_protocol_hash=data["selection_protocol_hash"],
            selection_manifest_hash=data["selection_manifest_hash"],
            source_revision=data["source_revision"],
        )


@dataclass(frozen=True)
class SolverRunAdapterReceipt(StrictCanonicalRecord):
    """Canonical adapter output for one solver-run checkpoint or export.

    A benchmark-specific adapter derives this receipt from the retained
    checkpoint or export. The generic verifier rehashes that source file,
    reloads this exact canonical receipt, and checks its observation-subset
    digest against the parity input before the run is admitted.
    """

    arm_role: ArmRole
    arm_id: str
    model_route_id: str
    run_manifest_digest: str
    checkpoint_export_sha256: str
    adapter_id: str
    adapter_code_sha256: str
    observed_provider_model_identity: str
    observed_response_count: int
    observation_subset_sha256: str
    observation_subset_hash_algorithm: str = SOLVER_OBSERVATION_SUBSET_HASH_ALGORITHM
    schema_version: str = RUN_ADAPTER_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_ADAPTER_RECEIPT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported solver run adapter receipt schema "
                f"{self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "arm_role",
            _enum(ArmRole, self.arm_role, "solver run adapter receipt arm role"),
        )
        for name in (
            "arm_id",
            "model_route_id",
            "adapter_id",
            "observed_provider_model_identity",
        ):
            _text(f"solver run adapter receipt {name}", getattr(self, name))
        for name in (
            "run_manifest_digest",
            "checkpoint_export_sha256",
            "adapter_code_sha256",
            "observation_subset_sha256",
        ):
            _hash(name, getattr(self, name))
        if (
            isinstance(self.observed_response_count, bool)
            or not isinstance(self.observed_response_count, int)
            or self.observed_response_count < 1
        ):
            raise ValueError(
                "solver run adapter receipt observed_response_count must be "
                "a positive integer"
            )
        if (
            self.observation_subset_hash_algorithm
            != SOLVER_OBSERVATION_SUBSET_HASH_ALGORITHM
        ):
            raise ValueError(
                "unsupported solver run adapter receipt observation-subset "
                "hash algorithm"
            )

    @property
    def key(self) -> tuple[ArmRole, str]:
        return (self.arm_role, self.model_route_id)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "arm_role": self.arm_role.value,
            "arm_id": self.arm_id,
            "model_route_id": self.model_route_id,
            "run_manifest_digest": self.run_manifest_digest,
            "checkpoint_export_sha256": self.checkpoint_export_sha256,
            "adapter_id": self.adapter_id,
            "adapter_code_sha256": self.adapter_code_sha256,
            "observed_provider_model_identity": (self.observed_provider_model_identity),
            "observed_response_count": self.observed_response_count,
            "observation_subset_hash_algorithm": (
                self.observation_subset_hash_algorithm
            ),
            "observation_subset_sha256": self.observation_subset_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["artifact_hash"] = _digest(payload)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SolverRunAdapterReceipt":
        fields = {
            "schema_version",
            "arm_role",
            "arm_id",
            "model_route_id",
            "run_manifest_digest",
            "checkpoint_export_sha256",
            "adapter_id",
            "adapter_code_sha256",
            "observed_provider_model_identity",
            "observed_response_count",
            "observation_subset_hash_algorithm",
            "observation_subset_sha256",
            "artifact_hash",
        }
        _fields(data, fields, "solver run adapter receipt")
        _hash("solver run adapter receipt artifact_hash", data["artifact_hash"])
        payload = {name: data[name] for name in fields - {"artifact_hash"}}
        if _digest(payload) != data["artifact_hash"]:
            raise ValueError("solver run adapter receipt artifact hash mismatch")
        result = cls(
            schema_version=data["schema_version"],
            arm_role=data["arm_role"],
            arm_id=data["arm_id"],
            model_route_id=data["model_route_id"],
            run_manifest_digest=data["run_manifest_digest"],
            checkpoint_export_sha256=data["checkpoint_export_sha256"],
            adapter_id=data["adapter_id"],
            adapter_code_sha256=data["adapter_code_sha256"],
            observed_provider_model_identity=(data["observed_provider_model_identity"]),
            observed_response_count=data["observed_response_count"],
            observation_subset_hash_algorithm=(
                data["observation_subset_hash_algorithm"]
            ),
            observation_subset_sha256=data["observation_subset_sha256"],
        )
        if result.digest != data["artifact_hash"]:
            raise ValueError("solver run adapter receipt is not canonical")
        return result

    @property
    def digest(self) -> str:
        return _digest(self._payload())


@dataclass(frozen=True)
class SolverRunEvidence(StrictCanonicalRecord):
    """Run and provider identity evidence for one arm and one solver route.

    ``raw_identity_checkpoint_sha256`` is the byte hash of the retained raw
    provider-identity and checkpoint evidence. The bytes remain external to
    this generic artifact and must be retained by the study operator.
    """

    arm_role: ArmRole
    arm_id: str
    model_route: ModelRoute
    run_manifest: RunManifest
    run_manifest_digest: str
    run_manifest_file_sha256: str
    expected_provider_model_identity: str
    observed_provider_model_identity: str
    raw_identity_checkpoint_sha256: str
    expected_response_count: int
    observed_response_count: int
    adapter_receipt: SolverRunAdapterReceipt
    adapter_receipt_file_sha256: str
    schema_version: str = RUN_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported solver run evidence schema {self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "arm_role",
            _enum(ArmRole, self.arm_role, "solver run evidence arm role"),
        )
        _text("solver run evidence arm_id", self.arm_id)
        if not isinstance(self.model_route, ModelRoute):
            raise ValueError("solver run evidence model_route must be ModelRoute")
        if not isinstance(self.run_manifest, RunManifest):
            raise ValueError("solver run evidence run_manifest must be RunManifest")
        for name in (
            "run_manifest_digest",
            "run_manifest_file_sha256",
            "raw_identity_checkpoint_sha256",
            "adapter_receipt_file_sha256",
        ):
            _hash(name, getattr(self, name))
        for name in (
            "expected_provider_model_identity",
            "observed_provider_model_identity",
        ):
            _text(name, getattr(self, name))
        if (
            self.observed_provider_model_identity
            != self.expected_provider_model_identity
        ):
            raise ValueError(
                "observed provider model identity does not match the "
                "predeclared expected identity"
            )
        for name in ("expected_response_count", "observed_response_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.observed_response_count != self.expected_response_count:
            raise ValueError(
                "observed response count does not match the expected response count"
            )
        if self.run_manifest.digest != self.run_manifest_digest:
            raise ValueError("solver run evidence run manifest digest is stale")
        if self.run_manifest.benchmark_arm != self.arm_id:
            raise ValueError(
                "solver run evidence arm ID does not match its run manifest"
            )
        if (
            self.run_manifest.provider != self.model_route.provider
            or self.run_manifest.model != self.model_route.model
        ):
            raise ValueError(
                "run manifest provider/model does not match the requested model route"
            )
        route_bindings = (
            (
                RUN_MANIFEST_ROUTE_SNAPSHOT_KEY,
                self.model_route.snapshot,
                "snapshot",
            ),
            (
                RUN_MANIFEST_ROUTE_FAMILY_KEY,
                self.model_route.family,
                "family",
            ),
            (
                RUN_MANIFEST_RUNTIME_CONFIG_HASH_KEY,
                self.model_route.runtime_config_hash,
                "runtime-config hash",
            ),
        )
        for key, expected, label in route_bindings:
            if self.run_manifest.model_config.get(key) != expected:
                raise ValueError(
                    f"run manifest requested {label} does not match the model route"
                )
        if (
            self.run_manifest.model_config.get(
                RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY
            )
            != self.expected_provider_model_identity
        ):
            raise ValueError(
                "expected provider model identity is not predeclared in the "
                "run manifest"
            )
        if not isinstance(self.adapter_receipt, SolverRunAdapterReceipt):
            raise ValueError(
                "solver run evidence adapter_receipt must be " "SolverRunAdapterReceipt"
            )
        receipt = self.adapter_receipt
        receipt_checks = (
            ("arm role", receipt.arm_role, self.arm_role),
            ("arm ID", receipt.arm_id, self.arm_id),
            ("model route", receipt.model_route_id, self.model_route.route_id),
            (
                "run manifest",
                receipt.run_manifest_digest,
                self.run_manifest_digest,
            ),
            (
                "checkpoint/export",
                receipt.checkpoint_export_sha256,
                self.raw_identity_checkpoint_sha256,
            ),
            (
                "observed provider model identity",
                receipt.observed_provider_model_identity,
                self.observed_provider_model_identity,
            ),
            (
                "observed response count",
                receipt.observed_response_count,
                self.observed_response_count,
            ),
        )
        for label, actual, expected in receipt_checks:
            if actual != expected:
                raise ValueError(
                    f"solver run adapter receipt {label} does not match its "
                    "solver run evidence"
                )
        if (
            self.run_manifest.model_config.get(RUN_MANIFEST_ADAPTER_CODE_HASH_KEY)
            != receipt.adapter_code_sha256
        ):
            raise ValueError(
                "solver run adapter code hash is not predeclared in the run " "manifest"
            )

    @property
    def key(self) -> tuple[ArmRole, str]:
        """Return the unique arm-role and solver-route coordinate."""

        return (self.arm_role, self.model_route.route_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "arm_role": self.arm_role.value,
            "arm_id": self.arm_id,
            "model_route": self.model_route.to_dict(),
            "run_manifest": self.run_manifest.to_dict(),
            "run_manifest_digest": self.run_manifest_digest,
            "run_manifest_file_sha256": self.run_manifest_file_sha256,
            "expected_provider_model_identity": (self.expected_provider_model_identity),
            "observed_provider_model_identity": (self.observed_provider_model_identity),
            "raw_identity_checkpoint_sha256": (self.raw_identity_checkpoint_sha256),
            "expected_response_count": self.expected_response_count,
            "observed_response_count": self.observed_response_count,
            "adapter_receipt": self.adapter_receipt.to_dict(),
            "adapter_receipt_file_sha256": self.adapter_receipt_file_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SolverRunEvidence":
        _fields(
            data,
            {
                "schema_version",
                "arm_role",
                "arm_id",
                "model_route",
                "run_manifest",
                "run_manifest_digest",
                "run_manifest_file_sha256",
                "expected_provider_model_identity",
                "observed_provider_model_identity",
                "raw_identity_checkpoint_sha256",
                "expected_response_count",
                "observed_response_count",
                "adapter_receipt",
                "adapter_receipt_file_sha256",
            },
            "solver run evidence",
        )
        if not isinstance(data["model_route"], Mapping):
            raise ValueError("solver run evidence model_route must be an object")
        if not isinstance(data["run_manifest"], Mapping):
            raise ValueError("solver run evidence run_manifest must be an object")
        if not isinstance(data["adapter_receipt"], Mapping):
            raise ValueError("solver run evidence adapter_receipt must be an object")
        return cls(
            schema_version=data["schema_version"],
            arm_role=data["arm_role"],
            arm_id=data["arm_id"],
            model_route=ModelRoute.from_dict(data["model_route"]),
            run_manifest=RunManifest.from_dict(data["run_manifest"]),
            run_manifest_digest=data["run_manifest_digest"],
            run_manifest_file_sha256=data["run_manifest_file_sha256"],
            expected_provider_model_identity=data["expected_provider_model_identity"],
            observed_provider_model_identity=data["observed_provider_model_identity"],
            raw_identity_checkpoint_sha256=data["raw_identity_checkpoint_sha256"],
            expected_response_count=data["expected_response_count"],
            observed_response_count=data["observed_response_count"],
            adapter_receipt=SolverRunAdapterReceipt.from_dict(data["adapter_receipt"]),
            adapter_receipt_file_sha256=data["adapter_receipt_file_sha256"],
        )


@dataclass(frozen=True)
class VariantSlot:
    """One aligned logical slot with independent arm-specific variant IDs."""

    slot_id: str
    kind: VariantSlotKind
    real_variant_id: str
    synthetic_variant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(VariantSlotKind, self.kind, "variant slot kind")
        )
        for name in ("slot_id", "real_variant_id", "synthetic_variant_id"):
            _text(name, getattr(self, name))
        if self.real_variant_id == self.synthetic_variant_id:
            raise ValueError("real and synthetic variant IDs must be distinct")

    def variant_id(self, role: ArmRole) -> str:
        if role is ArmRole.REAL:
            return self.real_variant_id
        if role is ArmRole.SYNTHETIC:
            return self.synthetic_variant_id
        raise ValueError(f"unsupported arm role {role!r}")

    def to_dict(self) -> dict[str, str]:
        return {
            "slot_id": self.slot_id,
            "kind": self.kind.value,
            "real_variant_id": self.real_variant_id,
            "synthetic_variant_id": self.synthetic_variant_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VariantSlot":
        _fields(
            data,
            {"slot_id", "kind", "real_variant_id", "synthetic_variant_id"},
            "variant slot",
        )
        return cls(
            slot_id=data["slot_id"],
            kind=data["kind"],
            real_variant_id=data["real_variant_id"],
            synthetic_variant_id=data["synthetic_variant_id"],
        )


@dataclass(frozen=True)
class SelectionPair:
    """One precommitted pair of real and synthetic case-family clusters."""

    pair_id: str
    real_case_family_id: str
    synthetic_case_family_id: str
    specialty: str
    sub_benchmark: str
    track: BenchmarkTrack | str
    variant_slots: tuple[VariantSlot, ...]
    plan_cell_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "pair_id",
            "real_case_family_id",
            "synthetic_case_family_id",
            "specialty",
            "sub_benchmark",
        ):
            _text(name, getattr(self, name))
        object.__setattr__(
            self, "track", _enum(BenchmarkTrack, self.track, "selection pair track")
        )
        if self.plan_cell_id is not None:
            _text("selection pair plan_cell_id", self.plan_cell_id)
        slots = tuple(self.variant_slots)
        if not slots or not all(isinstance(slot, VariantSlot) for slot in slots):
            raise ValueError("selection pair must contain VariantSlot values")
        if len({slot.slot_id for slot in slots}) != len(slots):
            raise ValueError("selection pair contains duplicate logical slot IDs")
        for role in ArmRole:
            variant_ids = [slot.variant_id(role) for slot in slots]
            if len(set(variant_ids)) != len(variant_ids):
                raise ValueError(
                    f"selection pair contains duplicate {role.value} variant IDs"
                )
        object.__setattr__(
            self, "variant_slots", tuple(sorted(slots, key=lambda slot: slot.slot_id))
        )

    def case_family_id(self, role: ArmRole) -> str:
        if role is ArmRole.REAL:
            return self.real_case_family_id
        if role is ArmRole.SYNTHETIC:
            return self.synthetic_case_family_id
        raise ValueError(f"unsupported arm role {role!r}")

    def slot(self, slot_id: str) -> VariantSlot:
        for slot in self.variant_slots:
            if slot.slot_id == slot_id:
                return slot
        raise ValueError(
            f"logical variant slot {slot_id!r} is not in pair {self.pair_id!r}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "real_case_family_id": self.real_case_family_id,
            "synthetic_case_family_id": self.synthetic_case_family_id,
            "specialty": self.specialty,
            "sub_benchmark": self.sub_benchmark,
            "track": self.track.value,
            "variant_slots": [slot.to_dict() for slot in self.variant_slots],
            "plan_cell_id": self.plan_cell_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SelectionPair":
        _fields(
            data,
            {
                "pair_id",
                "real_case_family_id",
                "synthetic_case_family_id",
                "specialty",
                "sub_benchmark",
                "track",
                "variant_slots",
                "plan_cell_id",
            },
            "selection pair",
        )
        return cls(
            pair_id=data["pair_id"],
            real_case_family_id=data["real_case_family_id"],
            synthetic_case_family_id=data["synthetic_case_family_id"],
            specialty=data["specialty"],
            sub_benchmark=data["sub_benchmark"],
            track=data["track"],
            variant_slots=tuple(
                VariantSlot.from_dict(value) for value in data["variant_slots"]
            ),
            plan_cell_id=data["plan_cell_id"],
        )


@dataclass(frozen=True)
class SelectionManifest(StrictCanonicalRecord):
    """Outcome-blind, precommitted pairing and selection evidence."""

    protocol_hash: str
    pairing_code_hash: str
    real_selection_hash: str
    synthetic_selection_hash: str
    selection_commit_hash: str
    basis: SelectionBasis
    selection_fields: tuple[str, ...]
    outcome_blind: bool
    committed_before_evaluation: bool
    uses_evaluated_outcomes: bool
    pairs: tuple[SelectionPair, ...]

    def __post_init__(self) -> None:
        for name in (
            "protocol_hash",
            "pairing_code_hash",
            "real_selection_hash",
            "synthetic_selection_hash",
            "selection_commit_hash",
        ):
            _hash(name, getattr(self, name))
        object.__setattr__(
            self, "basis", _enum(SelectionBasis, self.basis, "selection basis")
        )
        fields = tuple(self.selection_fields)
        if not fields:
            raise ValueError("selection_fields must not be empty")
        for field in fields:
            _text("selection field", field)
        if len(set(fields)) != len(fields):
            raise ValueError("selection_fields must be unique")
        object.__setattr__(self, "selection_fields", tuple(sorted(fields)))
        for name in (
            "outcome_blind",
            "committed_before_evaluation",
            "uses_evaluated_outcomes",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if self.basis is SelectionBasis.EVALUATED_OUTCOMES:
            raise ValueError("selection cannot be based on evaluated outcomes")
        if self.uses_evaluated_outcomes:
            raise ValueError("selection cannot use evaluated outcomes")
        if not self.outcome_blind:
            raise ValueError("selection must be outcome blind")
        if not self.committed_before_evaluation:
            raise ValueError("selection must be committed before evaluation")
        pairs = tuple(self.pairs)
        if not pairs or not all(isinstance(pair, SelectionPair) for pair in pairs):
            raise ValueError("selection manifest must contain SelectionPair values")
        if len({pair.pair_id for pair in pairs}) != len(pairs):
            raise ValueError("selection manifest contains duplicate pair IDs")
        for role in ArmRole:
            case_ids = [pair.case_family_id(role) for pair in pairs]
            if len(set(case_ids)) != len(case_ids):
                raise ValueError(
                    f"selection manifest contains duplicate {role.value} case-family IDs"
                )
            variant_ids = [
                slot.variant_id(role) for pair in pairs for slot in pair.variant_slots
            ]
            if len(set(variant_ids)) != len(variant_ids):
                raise ValueError(
                    f"selection manifest contains duplicate {role.value} variant IDs"
                )
        object.__setattr__(
            self,
            "pairs",
            tuple(sorted(pairs, key=lambda pair: pair.pair_id)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_hash": self.protocol_hash,
            "pairing_code_hash": self.pairing_code_hash,
            "real_selection_hash": self.real_selection_hash,
            "synthetic_selection_hash": self.synthetic_selection_hash,
            "selection_commit_hash": self.selection_commit_hash,
            "basis": self.basis.value,
            "selection_fields": list(self.selection_fields),
            "outcome_blind": self.outcome_blind,
            "committed_before_evaluation": self.committed_before_evaluation,
            "uses_evaluated_outcomes": self.uses_evaluated_outcomes,
            "pairs": [pair.to_dict() for pair in self.pairs],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SelectionManifest":
        _fields(
            data,
            {
                "protocol_hash",
                "pairing_code_hash",
                "real_selection_hash",
                "synthetic_selection_hash",
                "selection_commit_hash",
                "basis",
                "selection_fields",
                "outcome_blind",
                "committed_before_evaluation",
                "uses_evaluated_outcomes",
                "pairs",
            },
            "selection manifest",
        )
        return cls(
            protocol_hash=data["protocol_hash"],
            pairing_code_hash=data["pairing_code_hash"],
            real_selection_hash=data["real_selection_hash"],
            synthetic_selection_hash=data["synthetic_selection_hash"],
            selection_commit_hash=data["selection_commit_hash"],
            basis=data["basis"],
            selection_fields=tuple(data["selection_fields"]),
            outcome_blind=data["outcome_blind"],
            committed_before_evaluation=data["committed_before_evaluation"],
            uses_evaluated_outcomes=data["uses_evaluated_outcomes"],
            pairs=tuple(SelectionPair.from_dict(value) for value in data["pairs"]),
        )


@dataclass(frozen=True)
class EndpointObservation:
    """One scalar endpoint value from one model trial and case family."""

    arm_role: ArmRole
    specialty: str
    sub_benchmark: str
    model_id: str
    model_family: str
    case_family_id: str
    variant_slot_id: str
    variant_id: str
    trial: int
    endpoint: str
    value: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "arm_role", _enum(ArmRole, self.arm_role, "observation arm role")
        )
        for name in (
            "specialty",
            "sub_benchmark",
            "model_id",
            "model_family",
            "case_family_id",
            "variant_slot_id",
            "variant_id",
            "endpoint",
        ):
            _text(name, getattr(self, name))
        if isinstance(self.trial, bool) or not isinstance(self.trial, int):
            raise ValueError("trial must be an integer")
        if self.trial < 1:
            raise ValueError("trial must be positive")
        object.__setattr__(self, "value", _finite("observation value", self.value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm_role": self.arm_role.value,
            "specialty": self.specialty,
            "sub_benchmark": self.sub_benchmark,
            "model_id": self.model_id,
            "model_family": self.model_family,
            "case_family_id": self.case_family_id,
            "variant_slot_id": self.variant_slot_id,
            "variant_id": self.variant_id,
            "trial": self.trial,
            "endpoint": self.endpoint,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EndpointObservation":
        _fields(
            data,
            {
                "arm_role",
                "specialty",
                "sub_benchmark",
                "model_id",
                "model_family",
                "case_family_id",
                "variant_slot_id",
                "variant_id",
                "trial",
                "endpoint",
                "value",
            },
            "endpoint observation",
        )
        return cls(
            arm_role=data["arm_role"],
            specialty=data["specialty"],
            sub_benchmark=data["sub_benchmark"],
            model_id=data["model_id"],
            model_family=data["model_family"],
            case_family_id=data["case_family_id"],
            variant_slot_id=data["variant_slot_id"],
            variant_id=data["variant_id"],
            trial=data["trial"],
            endpoint=data["endpoint"],
            value=data["value"],
        )


def canonical_solver_observation_subset_sha256(
    observations: Sequence[EndpointObservation],
    *,
    arm_role: ArmRole | str,
    model_id: str,
) -> str:
    """Hash one exact arm-by-solver endpoint-observation subset.

    The role and model coordinate are part of the payload, so an identical
    value table cannot be relabelled as another solver-run cell without
    changing the digest.
    """

    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise ValueError("observations must be an endpoint-observation sequence")
    normalized_role = _enum(
        ArmRole,
        arm_role,
        "solver observation-subset arm role",
    )
    _text("solver observation-subset model_id", model_id)
    values = tuple(observations)
    if not all(isinstance(value, EndpointObservation) for value in values):
        raise ValueError("observations must contain EndpointObservation values")
    subset = tuple(
        sorted(
            (
                value
                for value in values
                if value.arm_role is normalized_role and value.model_id == model_id
            ),
            key=_observation_key,
        )
    )
    if not subset:
        raise ValueError(
            "solver observation subset must contain at least one observation"
        )
    return _digest(
        {
            "algorithm": SOLVER_OBSERVATION_SUBSET_HASH_ALGORITHM,
            "arm_role": normalized_role.value,
            "model_id": model_id,
            "observations": [value.to_dict() for value in subset],
        }
    )


@dataclass(frozen=True)
class SyntheticParityInput(StrictCanonicalRecord):
    """Complete hash-bound input table for a real-versus-synthetic study."""

    study_id: str
    program_hash: str
    comparison_id: str
    registry_hash: str
    archetype_hash: str
    evaluation_contract_hash: str
    decision_rule_hash: str
    benchmark_archetype: str
    specialty: str
    track: BenchmarkTrack | str
    endpoint: str
    trials: int
    arms: tuple[BenchmarkArm, ...]
    model_panel: tuple[ModelIdentity, ...]
    run_evidence: tuple[SolverRunEvidence, ...]
    selection: SelectionManifest
    observations: tuple[EndpointObservation, ...]
    source_results_hash: str
    extraction_code_hash: str
    schema_version: str = INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != INPUT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported synthetic parity input schema {self.schema_version!r}"
            )
        for name in (
            "study_id",
            "comparison_id",
            "benchmark_archetype",
            "specialty",
            "endpoint",
        ):
            _text(name, getattr(self, name))
        object.__setattr__(
            self, "track", _enum(BenchmarkTrack, self.track, "parity input track")
        )
        if (
            isinstance(self.trials, bool)
            or not isinstance(self.trials, int)
            or self.trials < 1
        ):
            raise ValueError("trials must be a positive integer")
        for name in (
            "program_hash",
            "registry_hash",
            "archetype_hash",
            "evaluation_contract_hash",
            "decision_rule_hash",
            "source_results_hash",
            "extraction_code_hash",
        ):
            _hash(name, getattr(self, name))

        arms = tuple(self.arms)
        if len(arms) != 2 or not all(isinstance(arm, BenchmarkArm) for arm in arms):
            raise ValueError("arms must contain exactly two BenchmarkArm values")
        by_role = {arm.role: arm for arm in arms}
        if set(by_role) != set(ArmRole) or len(by_role) != len(arms):
            raise ValueError("arms must contain exactly one real and one synthetic arm")
        if len({arm.arm_id for arm in arms}) != 2:
            raise ValueError("benchmark arm IDs must be distinct")
        if len({arm.content_hash for arm in arms}) != 2:
            raise ValueError("real and synthetic content hashes must be distinct")
        if len({arm.evaluation_contract_hash for arm in arms}) != 1:
            raise ValueError("benchmark arms must share the exact evaluation contract")
        if any(
            arm.evaluation_contract_hash != self.evaluation_contract_hash
            for arm in arms
        ):
            raise ValueError(
                "benchmark arms do not bind the program evaluation contract"
            )
        if any(
            arm.selection_protocol_hash != self.selection.protocol_hash for arm in arms
        ):
            raise ValueError("benchmark arms do not bind the selection protocol")
        if (
            by_role[ArmRole.REAL].selection_manifest_hash
            != self.selection.real_selection_hash
            or by_role[ArmRole.SYNTHETIC].selection_manifest_hash
            != self.selection.synthetic_selection_hash
        ):
            raise ValueError("benchmark arms do not bind their selection manifests")
        object.__setattr__(
            self, "arms", tuple(sorted(arms, key=lambda arm: arm.role.value))
        )

        panel = tuple(self.model_panel)
        if not 3 <= len(panel) <= 4:
            raise ValueError("model_panel must contain exactly 3 or 4 models")
        if not all(isinstance(model, ModelIdentity) for model in panel):
            raise ValueError("model_panel must contain ModelIdentity values")
        if len({model.model_id for model in panel}) != len(panel):
            raise ValueError("model_panel contains duplicate model IDs")
        if len({model.model_family for model in panel}) != len(panel):
            raise ValueError(
                "model_panel must contain exactly 3 or 4 distinct model families"
            )
        object.__setattr__(
            self,
            "model_panel",
            tuple(sorted(panel, key=lambda model: model.model_id)),
        )

        if not isinstance(self.selection, SelectionManifest):
            raise ValueError("selection must be a SelectionManifest")
        if any(pair.specialty != self.specialty for pair in self.selection.pairs):
            raise ValueError(
                "selection pairs must all belong to the bound comparison specialty"
            )
        if any(pair.track is not self.track for pair in self.selection.pairs):
            raise ValueError(
                "selection pairs must all belong to the exact bound comparison track"
            )
        slot_patterns = {
            tuple(sorted(slot.kind.value for slot in pair.variant_slots))
            for pair in self.selection.pairs
        }
        if len(slot_patterns) != 1:
            raise ValueError(
                "all selected case families must use the same variant-slot "
                "count and kind pattern"
            )
        normalized_endpoint = _normalize_field(self.endpoint)
        if normalized_endpoint in {
            _normalize_field(field) for field in self.selection.selection_fields
        }:
            raise ValueError("selection fields cannot include the evaluated endpoint")

        expected_response_count = (
            sum(len(pair.variant_slots) for pair in self.selection.pairs) * self.trials
        )
        run_evidence = tuple(self.run_evidence)
        if not run_evidence or not all(
            isinstance(value, SolverRunEvidence) for value in run_evidence
        ):
            raise ValueError(
                "run_evidence must contain SolverRunEvidence values for every "
                "arm and solver"
            )
        expected_run_keys = {
            (role, model.model_id) for role in ArmRole for model in self.model_panel
        }
        actual_run_keys = {value.key for value in run_evidence}
        if (
            len(actual_run_keys) != len(run_evidence)
            or actual_run_keys != expected_run_keys
        ):
            raise ValueError(
                "run_evidence must contain exactly one record for every "
                "2-arm-by-model-panel cell"
            )
        if len({value.run_manifest_digest for value in run_evidence}) != len(
            run_evidence
        ):
            raise ValueError(
                "every arm-by-solver cell must bind a distinct run manifest"
            )
        if len({value.run_manifest_file_sha256 for value in run_evidence}) != len(
            run_evidence
        ):
            raise ValueError(
                "every arm-by-solver cell must bind a distinct run manifest file"
            )
        if len({value.raw_identity_checkpoint_sha256 for value in run_evidence}) != len(
            run_evidence
        ):
            raise ValueError(
                "every arm-by-solver cell must bind distinct raw "
                "identity/checkpoint evidence"
            )
        if len({value.adapter_receipt.digest for value in run_evidence}) != len(
            run_evidence
        ):
            raise ValueError(
                "every arm-by-solver cell must bind a distinct adapter receipt"
            )
        if len({value.adapter_receipt_file_sha256 for value in run_evidence}) != len(
            run_evidence
        ):
            raise ValueError(
                "every arm-by-solver cell must bind a distinct adapter receipt " "file"
            )
        arms_by_role = {arm.role: arm for arm in self.arms}
        models_by_id = {model.model_id: model for model in self.model_panel}
        routes_by_id: dict[str, dict[str, str]] = {}
        shared_assets_by_route: dict[
            str,
            tuple[str, str, str | None, str, str, str, str],
        ] = {}
        for evidence in run_evidence:
            arm = arms_by_role[evidence.arm_role]
            model = models_by_id[evidence.model_route.route_id]
            if evidence.arm_id != arm.arm_id:
                raise ValueError(
                    "solver run evidence arm does not match the benchmark arm"
                )
            if (
                evidence.model_route.route_id != model.model_id
                or evidence.model_route.family != model.model_family
            ):
                raise ValueError(
                    "solver run evidence route does not match the model panel"
                )
            route_payload = evidence.model_route.to_dict()
            prior_route = routes_by_id.setdefault(
                evidence.model_route.route_id, route_payload
            )
            if prior_route != route_payload:
                raise ValueError(
                    "real and synthetic run evidence must use the exact same "
                    "requested model route"
                )
            manifest = evidence.run_manifest
            shared_assets = (
                manifest.prompt_hash,
                manifest.code_hash,
                manifest.judge_hash,
                evidence.adapter_receipt.adapter_id,
                evidence.adapter_receipt.adapter_code_sha256,
                evidence.expected_provider_model_identity,
                evidence.observed_provider_model_identity,
            )
            prior_assets = shared_assets_by_route.setdefault(
                evidence.model_route.route_id, shared_assets
            )
            if prior_assets != shared_assets:
                raise ValueError(
                    "real and synthetic run manifests must use the same prompt, "
                    "runner code, judge assets, adapter identity/code, and "
                    "provider model identity for each solver route"
                )
            if manifest.benchmark_content_hash != arm.content_hash:
                raise ValueError(
                    "run manifest benchmark content does not match its benchmark arm"
                )
            if manifest.source_revision != arm.source_revision:
                raise ValueError(
                    "run manifest source revision does not match its benchmark arm"
                )
            if manifest.trials != self.trials:
                raise ValueError(
                    "run manifest trial count does not match the parity input"
                )
            if (
                manifest.selection.get(RUN_MANIFEST_SELECTION_HASH_KEY)
                != arm.selection_manifest_hash
            ):
                raise ValueError(
                    "run manifest selection does not match its benchmark arm"
                )
            if (
                manifest.selection.get(RUN_MANIFEST_SELECTION_PROTOCOL_HASH_KEY)
                != arm.selection_protocol_hash
            ):
                raise ValueError(
                    "run manifest selection protocol does not match its "
                    "benchmark arm"
                )
            if (
                manifest.selection.get(RUN_MANIFEST_EVALUATION_CONTRACT_HASH_KEY)
                != arm.evaluation_contract_hash
            ):
                raise ValueError(
                    "run manifest evaluation contract does not match its "
                    "benchmark arm"
                )
            if evidence.expected_response_count != expected_response_count:
                raise ValueError(
                    "solver run evidence response count does not match the "
                    "selected arm workload"
                )
        object.__setattr__(
            self,
            "run_evidence",
            tuple(
                sorted(
                    run_evidence,
                    key=lambda value: (
                        value.arm_role.value,
                        value.model_route.route_id,
                    ),
                )
            ),
        )

        observations = tuple(self.observations)
        if not observations or not all(
            isinstance(value, EndpointObservation) for value in observations
        ):
            raise ValueError("observations must contain EndpointObservation values")
        self._validate_observations(observations)
        observed_response_counts = Counter(
            (value.arm_role, value.model_id) for value in observations
        )
        for evidence in self.run_evidence:
            if (
                observed_response_counts[evidence.key]
                != evidence.observed_response_count
            ):
                raise ValueError(
                    "solver run evidence response count does not match the "
                    "imported endpoint observations"
                )
            observed_subset_sha256 = canonical_solver_observation_subset_sha256(
                observations,
                arm_role=evidence.arm_role,
                model_id=evidence.model_route.route_id,
            )
            if (
                evidence.adapter_receipt.observation_subset_sha256
                != observed_subset_sha256
            ):
                raise ValueError(
                    "solver run adapter receipt observation subset does not "
                    "match the imported endpoint observations"
                )
        object.__setattr__(
            self,
            "observations",
            tuple(sorted(observations, key=_observation_key)),
        )

    def _validate_observations(
        self, observations: tuple[EndpointObservation, ...]
    ) -> None:
        model_families = {
            model.model_id: model.model_family for model in self.model_panel
        }
        case_lookup: dict[tuple[ArmRole, str], SelectionPair] = {}
        for pair in self.selection.pairs:
            for role in ArmRole:
                case_lookup[(role, pair.case_family_id(role))] = pair

        seen: set[tuple[ArmRole, str, str, str, int]] = set()
        actual: set[tuple[ArmRole, str, str, str, int]] = set()
        for observation in observations:
            if observation.endpoint != self.endpoint:
                raise ValueError(
                    f"observation endpoint {observation.endpoint!r} does not match "
                    f"{self.endpoint!r}"
                )
            if observation.trial > self.trials:
                raise ValueError("observation trial exceeds the frozen trial count")
            expected_family = model_families.get(observation.model_id)
            if expected_family is None:
                raise ValueError(
                    f"observation uses model {observation.model_id!r} outside the panel"
                )
            if observation.model_family != expected_family:
                raise ValueError(
                    f"observation model family does not match {observation.model_id!r}"
                )
            pair = case_lookup.get((observation.arm_role, observation.case_family_id))
            if pair is None:
                raise ValueError(
                    "observation case family is not in the frozen paired selection"
                )
            if (
                observation.specialty != pair.specialty
                or observation.sub_benchmark != pair.sub_benchmark
            ):
                raise ValueError(
                    "observation specialty/sub-benchmark does not match selection"
                )
            try:
                slot = pair.slot(observation.variant_slot_id)
            except ValueError as exc:
                raise ValueError(
                    "observation logical variant slot is not in the frozen selection"
                ) from exc
            if observation.variant_id != slot.variant_id(observation.arm_role):
                raise ValueError(
                    "observation variant ID does not match its role-specific "
                    "frozen logical slot"
                )
            identity = (
                observation.arm_role,
                observation.case_family_id,
                observation.variant_slot_id,
                observation.model_id,
                observation.trial,
            )
            if identity in seen:
                raise ValueError("duplicate endpoint observation")
            seen.add(identity)
            actual.add(identity)

        expected = {
            (
                role,
                pair.case_family_id(role),
                slot.slot_id,
                model.model_id,
                trial,
            )
            for role in ArmRole
            for pair in self.selection.pairs
            for slot in pair.variant_slots
            for model in self.model_panel
            for trial in range(1, self.trials + 1)
        }
        if actual != expected:
            missing = sorted(
                expected - actual,
                key=lambda value: (
                    value[0].value,
                    value[1],
                    value[2],
                    value[3],
                    value[4],
                ),
            )
            extra = actual - expected
            detail = ""
            if missing:
                role, case, slot, model, trial = missing[0]
                detail = (
                    f"; first missing cell is {role.value}/{case}/{slot}/"
                    f"{model}/trial-{trial}"
                )
            if extra:
                detail += f"; {len(extra)} unexpected cells"
            raise ValueError(
                "observations must form an exact logical-slot-by-arm-by-case-family-"
                f"by-model-by-trial panel{detail}"
            )

    def validate_against_program(
        self,
        program: SyntheticBenchmarkProgram,
        *,
        allow_source_plan_subset: bool = False,
    ) -> None:
        """Verify every redundant binding against one program comparison.

        The default requires the complete comparison plan. Optimization may
        opt into a preregistered subset, which must later be validated against
        the exact program-bound full-corpus inventories and split manifest.
        """

        if not isinstance(program, SyntheticBenchmarkProgram):
            raise ValueError("program must be SyntheticBenchmarkProgram")
        if not isinstance(allow_source_plan_subset, bool):
            raise ValueError("allow_source_plan_subset must be boolean")
        if self.program_hash != program.digest:
            raise ValueError("parity input program hash does not match the program")
        comparison = program.comparison(self.comparison_id)
        archetype = program.registry.get(comparison.archetype_id)
        expected_contract = program.evaluation_contract_digest(self.comparison_id)
        checks = (
            ("registry hash", self.registry_hash, program.registry_digest),
            ("archetype hash", self.archetype_hash, archetype.digest),
            (
                "evaluation contract hash",
                self.evaluation_contract_hash,
                expected_contract,
            ),
            (
                "benchmark archetype",
                self.benchmark_archetype,
                ArchetypeId(comparison.archetype_id).value,
            ),
            ("specialty", self.specialty, comparison.specialty_id),
            ("track", self.track, comparison.track),
            ("endpoint", self.endpoint, comparison.endpoint_id),
            (
                "decision rule hash",
                self.decision_rule_hash,
                comparison.decision_rule_hash,
            ),
        )
        for label, actual, expected in checks:
            if actual != expected:
                raise ValueError(
                    f"parity input {label} does not match the program comparison"
                )

        by_role = {arm.role: arm for arm in self.arms}
        if (
            by_role[ArmRole.REAL].content_hash != comparison.reference.bundle_hash
            or by_role[ArmRole.SYNTHETIC].content_hash
            != comparison.synthetic.bundle_hash
        ):
            raise ValueError(
                "parity input benchmark arms do not match the program bundle hashes"
            )
        if any(arm.evaluation_contract_hash != expected_contract for arm in self.arms):
            raise ValueError(
                "parity input arms do not match the program evaluation contract"
            )

        source_binding = comparison.source_plan_binding
        if source_binding is not None:
            if self.track is not source_binding.track:
                raise ValueError(
                    "parity input track does not match the specialty source-plan "
                    "binding"
                )
            selected_family_count = len(self.selection.pairs)
            if allow_source_plan_subset:
                if selected_family_count > source_binding.planned_family_count:
                    raise ValueError(
                        "parity input case-family subset exceeds the specialty "
                        "source-plan binding"
                    )
            elif selected_family_count != source_binding.planned_family_count:
                raise ValueError(
                    "parity input case-family count does not match the specialty "
                    "source-plan binding"
                )
            expected_cell_counts = {
                cell.cell_id: cell.family_count for cell in source_binding.planned_cells
            }
            if any(pair.plan_cell_id is None for pair in self.selection.pairs):
                raise ValueError(
                    "every source-bound selection pair must name its exact "
                    "specialty plan cell"
                )
            observed_cell_counts = Counter(
                pair.plan_cell_id for pair in self.selection.pairs
            )
            unknown = sorted(
                cell_id
                for cell_id in observed_cell_counts
                if cell_id not in expected_cell_counts
            )
            if allow_source_plan_subset:
                mismatches = [
                    (
                        cell_id,
                        expected_count,
                        observed_cell_counts.get(cell_id, 0),
                    )
                    for cell_id, expected_count in sorted(expected_cell_counts.items())
                    if observed_cell_counts.get(cell_id, 0) > expected_count
                ]
            else:
                mismatches = [
                    (
                        cell_id,
                        expected_count,
                        observed_cell_counts.get(cell_id, 0),
                    )
                    for cell_id, expected_count in sorted(expected_cell_counts.items())
                    if observed_cell_counts.get(cell_id, 0) != expected_count
                ]
            if unknown or mismatches:
                detail_parts = []
                if unknown:
                    detail_parts.append(f"unknown cells {unknown}")
                if mismatches:
                    cell_id, expected_count, observed_count = mismatches[0]
                    detail_parts.append(
                        f"{cell_id!r} expected {expected_count}, observed "
                        f"{observed_count}"
                    )
                detail = "; ".join(detail_parts)
                raise ValueError(
                    "parity input case-family distribution does not match every "
                    f"specialty source-plan cell: {detail}"
                )
            if self.trials != source_binding.model_repetitions:
                raise ValueError(
                    "parity input trial count does not match the specialty "
                    "source-plan model repetitions"
                )

        endpoint_contract = archetype.endpoint(comparison.endpoint_id)
        if endpoint_contract.bounded_range is not None:
            lower, upper = endpoint_contract.bounded_range
            for observation in self.observations:
                if observation.value < lower or observation.value > upper:
                    raise ValueError(
                        f"observation value {observation.value!r} is outside the "
                        f"registered endpoint range [{lower}, {upper}] for "
                        f"{endpoint_contract.endpoint_id!r}"
                    )

        expected_panel = tuple(
            sorted((route.route_id, route.family) for route in program.solver_panel)
        )
        actual_panel = tuple(
            sorted((model.model_id, model.model_family) for model in self.model_panel)
        )
        if actual_panel != expected_panel:
            raise ValueError(
                "parity input model IDs and families do not match the exact "
                "program solver routes"
            )
        routes_by_id = {route.route_id: route for route in program.solver_panel}
        for evidence in self.run_evidence:
            expected_route = routes_by_id[evidence.model_route.route_id]
            if evidence.model_route.to_dict() != expected_route.to_dict():
                raise ValueError(
                    "solver run evidence requested route does not match the exact "
                    "program provider/model/snapshot/family/runtime configuration"
                )
            if (
                JudgePolicy(archetype.scorer_judge.judge_policy) is JudgePolicy.REQUIRED
                and evidence.run_manifest.judge_hash is None
            ):
                raise ValueError(
                    "solver run evidence must bind judge assets for this archetype"
                )

        topology = archetype.topology
        for pair in self.selection.pairs:
            slots = pair.variant_slots
            kinds = [slot.kind for slot in slots]
            if (
                topology.variant_selection_policy
                is VariantSelectionPolicy.BASELINE_PLUS_PERTURBATION_SUBSET
            ):
                maximum = topology.fixed_variants_per_family
                canonical = topology.canonical_evaluated_variants_per_family
                if (
                    maximum is None
                    or canonical is None
                    or len(slots) != canonical
                    or len(slots) > maximum
                    or kinds.count(VariantSlotKind.BASELINE) != 1
                    or kinds.count(VariantSlotKind.PERTURBATION) != len(slots) - 1
                ):
                    raise ValueError(
                        "NOHARM selection must contain exactly one baseline plus "
                        f"{canonical - 1 if canonical is not None else 'the frozen'} "
                        "perturbation slots for the canonical evaluated topology"
                    )
            elif topology.variant_selection_policy is VariantSelectionPolicy.FIXED:
                if len(slots) != topology.fixed_variants_per_family:
                    raise ValueError(
                        "selection slot count does not match the archetype's fixed "
                        "variant topology"
                    )
                if any(kind is not VariantSlotKind.VARIANT for kind in kinds):
                    raise ValueError(
                        "non-NOHARM fixed topology must use generic variant slots"
                    )
            elif any(kind is not VariantSlotKind.VARIANT for kind in kinds):
                raise ValueError(
                    "non-NOHARM variable topology must use generic variant slots"
                )

    def _payload(self) -> dict[str, Any]:
        observations = [value.to_dict() for value in self.observations]
        return {
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "program_hash": self.program_hash,
            "comparison_id": self.comparison_id,
            "registry_hash": self.registry_hash,
            "archetype_hash": self.archetype_hash,
            "evaluation_contract_hash": self.evaluation_contract_hash,
            "decision_rule_hash": self.decision_rule_hash,
            "benchmark_archetype": self.benchmark_archetype,
            "specialty": self.specialty,
            "track": self.track.value,
            "endpoint": self.endpoint,
            "trials": self.trials,
            "arms": [arm.to_dict() for arm in self.arms],
            "model_panel": [model.to_dict() for model in self.model_panel],
            "run_evidence": [value.to_dict() for value in self.run_evidence],
            "run_adapter_receipts_hash": self.run_adapter_receipts_hash,
            "selection": self.selection.to_dict(),
            "observations": observations,
            "observation_table_hash": _digest(observations),
            "source_results_hash": self.source_results_hash,
            "extraction_code_hash": self.extraction_code_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["artifact_hash"] = _digest(payload)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SyntheticParityInput":
        fields = {
            "schema_version",
            "study_id",
            "program_hash",
            "comparison_id",
            "registry_hash",
            "archetype_hash",
            "evaluation_contract_hash",
            "decision_rule_hash",
            "benchmark_archetype",
            "specialty",
            "track",
            "endpoint",
            "trials",
            "arms",
            "model_panel",
            "run_evidence",
            "run_adapter_receipts_hash",
            "selection",
            "observations",
            "observation_table_hash",
            "source_results_hash",
            "extraction_code_hash",
            "artifact_hash",
        }
        _fields(data, fields, "synthetic parity input")
        expected_hash = data["artifact_hash"]
        _hash("artifact_hash", expected_hash)
        raw_payload = {key: data[key] for key in fields - {"artifact_hash"}}
        if _digest(raw_payload) != expected_hash:
            raise ValueError("synthetic parity input artifact hash mismatch")
        observations_hash = _digest(data["observations"])
        if observations_hash != data["observation_table_hash"]:
            raise ValueError("synthetic parity observation table hash mismatch")
        result = cls(
            study_id=data["study_id"],
            program_hash=data["program_hash"],
            comparison_id=data["comparison_id"],
            registry_hash=data["registry_hash"],
            archetype_hash=data["archetype_hash"],
            evaluation_contract_hash=data["evaluation_contract_hash"],
            decision_rule_hash=data["decision_rule_hash"],
            benchmark_archetype=data["benchmark_archetype"],
            specialty=data["specialty"],
            track=data["track"],
            endpoint=data["endpoint"],
            trials=data["trials"],
            arms=tuple(BenchmarkArm.from_dict(value) for value in data["arms"]),
            model_panel=tuple(
                ModelIdentity.from_dict(value) for value in data["model_panel"]
            ),
            run_evidence=tuple(
                SolverRunEvidence.from_dict(value) for value in data["run_evidence"]
            ),
            selection=SelectionManifest.from_dict(data["selection"]),
            observations=tuple(
                EndpointObservation.from_dict(value) for value in data["observations"]
            ),
            source_results_hash=data["source_results_hash"],
            extraction_code_hash=data["extraction_code_hash"],
            schema_version=data["schema_version"],
        )
        if result.digest != expected_hash:
            raise ValueError("synthetic parity input is not canonically ordered")
        if data["run_adapter_receipts_hash"] != result.run_adapter_receipts_hash:
            raise ValueError("synthetic parity input run adapter receipt hash mismatch")
        return result

    @classmethod
    def from_json(cls, payload: str) -> "SyntheticParityInput":
        data = strict_json_loads(payload, "synthetic parity input", allow_bytes=True)
        return cls.from_dict(data)

    @property
    def observation_table_hash(self) -> str:
        return _digest([value.to_dict() for value in self.observations])

    @property
    def run_adapter_receipts_hash(self) -> str:
        return _digest([value.adapter_receipt.to_dict() for value in self.run_evidence])

    @property
    def digest(self) -> str:
        return _digest(self._payload())


@dataclass(frozen=True)
class ParityDecisionRule:
    """Frozen confidence and equivalence requirements."""

    per_model_delta_margin: float
    absolute_difficulty_shift_margin: float
    minimum_rank_agreement: float
    minimum_discrimination_spread_ratio: float
    maximum_discrimination_spread_ratio: float
    confidence_level: float
    bootstrap_draws: int
    bootstrap_seed: int
    minimum_case_family_pairs_per_scope: int
    schema_version: str = RULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RULE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported synthetic parity rule schema {self.schema_version!r}"
            )
        for name in (
            "per_model_delta_margin",
            "absolute_difficulty_shift_margin",
        ):
            value = _finite(name, getattr(self, name))
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        rank = _finite("minimum_rank_agreement", self.minimum_rank_agreement)
        if not -1.0 <= rank <= 1.0:
            raise ValueError("minimum_rank_agreement must be between -1 and 1")
        object.__setattr__(self, "minimum_rank_agreement", rank)
        lower = _finite(
            "minimum_discrimination_spread_ratio",
            self.minimum_discrimination_spread_ratio,
        )
        upper = _finite(
            "maximum_discrimination_spread_ratio",
            self.maximum_discrimination_spread_ratio,
        )
        if lower <= 0 or upper < lower:
            raise ValueError("discrimination spread ratio bounds are invalid")
        object.__setattr__(self, "minimum_discrimination_spread_ratio", lower)
        object.__setattr__(self, "maximum_discrimination_spread_ratio", upper)
        confidence = _finite("confidence_level", self.confidence_level)
        if not 0.0 < confidence < 1.0:
            raise ValueError("confidence_level must be between zero and one")
        object.__setattr__(self, "confidence_level", confidence)
        if (
            isinstance(self.bootstrap_draws, bool)
            or not isinstance(self.bootstrap_draws, int)
            or self.bootstrap_draws < 1
        ):
            raise ValueError("bootstrap_draws must be a positive integer")
        if isinstance(self.bootstrap_seed, bool) or not isinstance(
            self.bootstrap_seed, int
        ):
            raise ValueError("bootstrap_seed must be an integer")
        if (
            isinstance(self.minimum_case_family_pairs_per_scope, bool)
            or not isinstance(self.minimum_case_family_pairs_per_scope, int)
            or self.minimum_case_family_pairs_per_scope < 2
        ):
            raise ValueError(
                "minimum_case_family_pairs_per_scope must be an integer of at "
                "least 2"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "per_model_delta_margin": self.per_model_delta_margin,
            "absolute_difficulty_shift_margin": (self.absolute_difficulty_shift_margin),
            "minimum_rank_agreement": self.minimum_rank_agreement,
            "minimum_discrimination_spread_ratio": (
                self.minimum_discrimination_spread_ratio
            ),
            "maximum_discrimination_spread_ratio": (
                self.maximum_discrimination_spread_ratio
            ),
            "confidence_level": self.confidence_level,
            "bootstrap_draws": self.bootstrap_draws,
            "bootstrap_seed": self.bootstrap_seed,
            "minimum_case_family_pairs_per_scope": (
                self.minimum_case_family_pairs_per_scope
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["artifact_hash"] = _digest(payload)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParityDecisionRule":
        fields = {
            "schema_version",
            "per_model_delta_margin",
            "absolute_difficulty_shift_margin",
            "minimum_rank_agreement",
            "minimum_discrimination_spread_ratio",
            "maximum_discrimination_spread_ratio",
            "confidence_level",
            "bootstrap_draws",
            "bootstrap_seed",
            "minimum_case_family_pairs_per_scope",
            "artifact_hash",
        }
        _fields(data, fields, "synthetic parity decision rule")
        payload = {key: data[key] for key in fields - {"artifact_hash"}}
        if _digest(payload) != data["artifact_hash"]:
            raise ValueError("synthetic parity decision rule artifact hash mismatch")
        result = cls(**payload)
        if result.digest != data["artifact_hash"]:
            raise ValueError("synthetic parity decision rule is not canonical")
        return result

    @property
    def digest(self) -> str:
        return _digest(self._payload())


@dataclass(frozen=True)
class ConfidenceInterval:
    """Closed percentile-bootstrap confidence interval."""

    lower: float
    upper: float
    confidence_level: float

    def __post_init__(self) -> None:
        lower = _finite("confidence interval lower", self.lower)
        upper = _finite("confidence interval upper", self.upper)
        confidence = _finite("confidence_level", self.confidence_level)
        if lower > upper:
            raise ValueError("confidence interval lower bound exceeds upper bound")
        if not 0.0 < confidence < 1.0:
            raise ValueError("confidence_level must be between zero and one")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "confidence_level", confidence)

    def to_dict(self) -> dict[str, float]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "confidence_level": self.confidence_level,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConfidenceInterval":
        _fields(
            data,
            {"lower", "upper", "confidence_level"},
            "confidence interval",
        )
        return cls(
            lower=data["lower"],
            upper=data["upper"],
            confidence_level=data["confidence_level"],
        )


@dataclass(frozen=True)
class EquivalenceMeasure:
    """One endpoint, including an explicit non-estimable state."""

    name: str
    estimate: float | None
    confidence_interval: ConfidenceInterval | None
    acceptable_lower: float
    acceptable_upper: float
    not_estimable_reason: str | None = None

    def __post_init__(self) -> None:
        _text("equivalence measure name", self.name)
        lower = _finite("acceptable_lower", self.acceptable_lower)
        upper = _finite("acceptable_upper", self.acceptable_upper)
        if lower > upper:
            raise ValueError("acceptable_lower exceeds acceptable_upper")
        object.__setattr__(self, "acceptable_lower", lower)
        object.__setattr__(self, "acceptable_upper", upper)
        if self.not_estimable_reason is not None:
            _text("not_estimable_reason", self.not_estimable_reason)
            if self.estimate is not None or self.confidence_interval is not None:
                raise ValueError(
                    "a non-estimable measure cannot contain an estimate or interval"
                )
            return
        if self.estimate is None or not isinstance(
            self.confidence_interval, ConfidenceInterval
        ):
            raise ValueError(
                "an estimable measure requires an estimate and confidence interval"
            )
        estimate = _finite("equivalence measure estimate", self.estimate)
        object.__setattr__(self, "estimate", estimate)
        if (
            not self.confidence_interval.lower
            <= estimate
            <= self.confidence_interval.upper
        ):
            raise ValueError("equivalence measure estimate must be inside its interval")

    @property
    def verdict(self) -> ParityVerdict:
        if self.not_estimable_reason is not None:
            return ParityVerdict.INCONCLUSIVE
        assert self.confidence_interval is not None
        interval = self.confidence_interval
        if (
            interval.lower >= self.acceptable_lower
            and interval.upper <= self.acceptable_upper
        ):
            return ParityVerdict.EQUIVALENT
        if (
            interval.upper < self.acceptable_lower
            or interval.lower > self.acceptable_upper
        ):
            return ParityVerdict.NON_EQUIVALENT
        return ParityVerdict.INCONCLUSIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "estimate": self.estimate,
            "confidence_interval": (
                self.confidence_interval.to_dict()
                if self.confidence_interval is not None
                else None
            ),
            "acceptable_lower": self.acceptable_lower,
            "acceptable_upper": self.acceptable_upper,
            "not_estimable_reason": self.not_estimable_reason,
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EquivalenceMeasure":
        _fields(
            data,
            {
                "name",
                "estimate",
                "confidence_interval",
                "acceptable_lower",
                "acceptable_upper",
                "not_estimable_reason",
                "verdict",
            },
            "equivalence measure",
        )
        result = cls(
            name=data["name"],
            estimate=data["estimate"],
            confidence_interval=(
                ConfidenceInterval.from_dict(data["confidence_interval"])
                if data["confidence_interval"] is not None
                else None
            ),
            acceptable_lower=data["acceptable_lower"],
            acceptable_upper=data["acceptable_upper"],
            not_estimable_reason=data["not_estimable_reason"],
        )
        if data["verdict"] != result.verdict.value:
            raise ValueError("equivalence measure verdict was not derived")
        return result


@dataclass(frozen=True)
class ModelParityResult:
    """Real score, synthetic score, and paired delta for one model."""

    model_id: str
    model_family: str
    real_score: float
    synthetic_score: float
    delta: EquivalenceMeasure

    def __post_init__(self) -> None:
        _text("model_id", self.model_id)
        _text("model_family", self.model_family)
        real = _finite("real_score", self.real_score)
        synthetic = _finite("synthetic_score", self.synthetic_score)
        if not isinstance(self.delta, EquivalenceMeasure):
            raise ValueError("delta must be EquivalenceMeasure")
        if self.delta.name != "synthetic-minus-real":
            raise ValueError("model delta measure has the wrong name")
        if not math.isclose(
            self.delta.estimate,
            synthetic - real,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("model delta does not equal synthetic minus real")
        object.__setattr__(self, "real_score", real)
        object.__setattr__(self, "synthetic_score", synthetic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "real_score": self.real_score,
            "synthetic_score": self.synthetic_score,
            "delta": self.delta.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelParityResult":
        _fields(
            data,
            {
                "model_id",
                "model_family",
                "real_score",
                "synthetic_score",
                "delta",
            },
            "model parity result",
        )
        return cls(
            model_id=data["model_id"],
            model_family=data["model_family"],
            real_score=data["real_score"],
            synthetic_score=data["synthetic_score"],
            delta=EquivalenceMeasure.from_dict(data["delta"]),
        )


@dataclass(frozen=True)
class ScopeParityResult:
    """Parity endpoints for the overall panel or a specialty scope."""

    specialty: str | None
    sub_benchmark: str | None
    case_family_pairs: int
    model_results: tuple[ModelParityResult, ...]
    absolute_difficulty_shift: EquivalenceMeasure
    rank_order_agreement: EquivalenceMeasure
    discrimination_spread_ratio: EquivalenceMeasure
    cluster_manifest_hash: str
    bootstrap_draws_hash: str

    def __post_init__(self) -> None:
        if self.specialty is not None:
            _text("scope specialty", self.specialty)
        if self.sub_benchmark is not None:
            _text("scope sub_benchmark", self.sub_benchmark)
            if self.specialty is None:
                raise ValueError("a sub-benchmark scope requires a specialty")
        if (
            isinstance(self.case_family_pairs, bool)
            or not isinstance(self.case_family_pairs, int)
            or self.case_family_pairs < 1
        ):
            raise ValueError("case_family_pairs must be positive")
        results = tuple(self.model_results)
        if not 3 <= len(results) <= 4 or not all(
            isinstance(value, ModelParityResult) for value in results
        ):
            raise ValueError("model_results must contain exactly 3 or 4 models")
        if len({result.model_id for result in results}) != len(results):
            raise ValueError("scope contains duplicate model results")
        object.__setattr__(
            self,
            "model_results",
            tuple(sorted(results, key=lambda result: result.model_id)),
        )
        for name, expected in (
            ("absolute_difficulty_shift", "absolute-difficulty-shift"),
            ("rank_order_agreement", "spearman-rank-order-agreement"),
            ("discrimination_spread_ratio", "discrimination-spread-ratio"),
        ):
            measure = getattr(self, name)
            if not isinstance(measure, EquivalenceMeasure):
                raise ValueError(f"{name} must be EquivalenceMeasure")
            if measure.name != expected:
                raise ValueError(f"{name} has the wrong measure name")
        for name in ("cluster_manifest_hash", "bootstrap_draws_hash"):
            _hash(name, getattr(self, name))

    @property
    def verdict(self) -> ParityVerdict:
        verdicts = [result.delta.verdict for result in self.model_results] + [
            self.absolute_difficulty_shift.verdict,
            self.rank_order_agreement.verdict,
            self.discrimination_spread_ratio.verdict,
        ]
        return _combine_verdicts(verdicts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "specialty": self.specialty,
            "sub_benchmark": self.sub_benchmark,
            "case_family_pairs": self.case_family_pairs,
            "model_results": [value.to_dict() for value in self.model_results],
            "absolute_difficulty_shift": self.absolute_difficulty_shift.to_dict(),
            "rank_order_agreement": self.rank_order_agreement.to_dict(),
            "discrimination_spread_ratio": (self.discrimination_spread_ratio.to_dict()),
            "cluster_manifest_hash": self.cluster_manifest_hash,
            "bootstrap_draws_hash": self.bootstrap_draws_hash,
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScopeParityResult":
        _fields(
            data,
            {
                "specialty",
                "sub_benchmark",
                "case_family_pairs",
                "model_results",
                "absolute_difficulty_shift",
                "rank_order_agreement",
                "discrimination_spread_ratio",
                "cluster_manifest_hash",
                "bootstrap_draws_hash",
                "verdict",
            },
            "scope parity result",
        )
        result = cls(
            specialty=data["specialty"],
            sub_benchmark=data["sub_benchmark"],
            case_family_pairs=data["case_family_pairs"],
            model_results=tuple(
                ModelParityResult.from_dict(value) for value in data["model_results"]
            ),
            absolute_difficulty_shift=EquivalenceMeasure.from_dict(
                data["absolute_difficulty_shift"]
            ),
            rank_order_agreement=EquivalenceMeasure.from_dict(
                data["rank_order_agreement"]
            ),
            discrimination_spread_ratio=EquivalenceMeasure.from_dict(
                data["discrimination_spread_ratio"]
            ),
            cluster_manifest_hash=data["cluster_manifest_hash"],
            bootstrap_draws_hash=data["bootstrap_draws_hash"],
        )
        if data["verdict"] != result.verdict.value:
            raise ValueError("scope parity verdict was not derived")
        return result


@dataclass(frozen=True)
class SyntheticParityReport(StrictCanonicalRecord):
    """Hash-bound parity result with overall and specialty diagnostics."""

    study_id: str
    program_hash: str
    comparison_id: str
    registry_hash: str
    archetype_hash: str
    evaluation_contract_hash: str
    benchmark_archetype: str
    specialty: str
    track: BenchmarkTrack | str
    endpoint: str
    input_hash: str
    source_results_hash: str
    run_adapter_receipts_hash: str
    decision_rule_hash: str
    decision_rule: ParityDecisionRule
    analysis_code_hash: str
    model_panel: tuple[ModelIdentity, ...]
    bootstrap_algorithm: str
    bootstrap_seed: int
    bootstrap_draws: int
    overall: ScopeParityResult
    specialty_results: tuple[ScopeParityResult, ...]
    sub_benchmark_results: tuple[ScopeParityResult, ...]
    verdict_scope: str = VERDICT_SCOPE
    artifact_hash_kind: str = ARTIFACT_HASH_KIND
    schema_version: str = REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported synthetic parity report schema {self.schema_version!r}"
            )
        for name in (
            "study_id",
            "comparison_id",
            "benchmark_archetype",
            "specialty",
            "endpoint",
        ):
            _text(name, getattr(self, name))
        object.__setattr__(
            self, "track", _enum(BenchmarkTrack, self.track, "parity report track")
        )
        for name in (
            "program_hash",
            "registry_hash",
            "archetype_hash",
            "evaluation_contract_hash",
            "input_hash",
            "source_results_hash",
            "run_adapter_receipts_hash",
            "decision_rule_hash",
            "analysis_code_hash",
        ):
            _hash(name, getattr(self, name))
        if not isinstance(self.decision_rule, ParityDecisionRule):
            raise ValueError("decision_rule must be ParityDecisionRule")
        if self.decision_rule_hash != self.decision_rule.digest:
            raise ValueError("report decision rule hash does not match the frozen rule")
        expected_verdict_scope = (
            REPRESENTATIVE_VERDICT_SCOPE
            if self.track is BenchmarkTrack.REPRESENTATIVE
            else STRESS_VERDICT_SCOPE
        )
        if self.verdict_scope != expected_verdict_scope:
            raise ValueError(
                "report verdict scope does not match the representative/stress "
                "track semantics"
            )
        if self.artifact_hash_kind != ARTIFACT_HASH_KIND:
            raise ValueError("report artifact hash kind is invalid")
        if self.bootstrap_algorithm != BOOTSTRAP_ALGORITHM:
            raise ValueError("unsupported synthetic parity bootstrap algorithm")
        if isinstance(self.bootstrap_seed, bool) or not isinstance(
            self.bootstrap_seed, int
        ):
            raise ValueError("bootstrap_seed must be an integer")
        if (
            isinstance(self.bootstrap_draws, bool)
            or not isinstance(self.bootstrap_draws, int)
            or self.bootstrap_draws < 1
        ):
            raise ValueError("bootstrap_draws must be positive")
        if (
            self.bootstrap_seed != self.decision_rule.bootstrap_seed
            or self.bootstrap_draws != self.decision_rule.bootstrap_draws
        ):
            raise ValueError("report bootstrap settings do not match the decision rule")
        panel = tuple(self.model_panel)
        if not 3 <= len(panel) <= 4 or not all(
            isinstance(model, ModelIdentity) for model in panel
        ):
            raise ValueError("model_panel must contain exactly 3 or 4 models")
        if len({model.model_id for model in panel}) != len(panel):
            raise ValueError("report model_panel contains duplicate model IDs")
        if len({model.model_family for model in panel}) != len(panel):
            raise ValueError("report model_panel must contain distinct model families")
        object.__setattr__(
            self,
            "model_panel",
            tuple(sorted(panel, key=lambda model: model.model_id)),
        )
        if not isinstance(self.overall, ScopeParityResult):
            raise ValueError("overall must be ScopeParityResult")
        if self.overall.specialty is not None:
            raise ValueError("overall scope cannot name a specialty")
        model_ids = tuple(model.model_id for model in self.model_panel)
        if tuple(result.model_id for result in self.overall.model_results) != model_ids:
            raise ValueError("overall result does not contain the exact model panel")
        specialties = tuple(self.specialty_results)
        sub_benchmarks = tuple(self.sub_benchmark_results)
        if not specialties or not all(
            isinstance(value, ScopeParityResult) for value in specialties
        ):
            raise ValueError("specialty_results must contain ScopeParityResult values")
        if not sub_benchmarks or not all(
            isinstance(value, ScopeParityResult) for value in sub_benchmarks
        ):
            raise ValueError(
                "sub_benchmark_results must contain ScopeParityResult values"
            )
        if any(
            result.specialty is None or result.sub_benchmark is not None
            for result in specialties
        ):
            raise ValueError("specialty_results contains an invalid scope")
        if any(
            result.specialty is None or result.sub_benchmark is None
            for result in sub_benchmarks
        ):
            raise ValueError("sub_benchmark_results contains an invalid scope")
        for result in (*specialties, *sub_benchmarks):
            if tuple(value.model_id for value in result.model_results) != model_ids:
                raise ValueError(
                    "subgroup result does not contain the exact model panel"
                )
        specialty_keys = [result.specialty for result in specialties]
        subgroup_keys = [
            (result.specialty, result.sub_benchmark) for result in sub_benchmarks
        ]
        if len(set(specialty_keys)) != len(specialty_keys):
            raise ValueError("report contains duplicate specialty results")
        if len(set(subgroup_keys)) != len(subgroup_keys):
            raise ValueError("report contains duplicate sub-benchmark results")
        if specialty_keys != [self.specialty]:
            raise ValueError(
                "report specialty diagnostics must contain the bound specialty"
            )
        object.__setattr__(
            self,
            "specialty_results",
            tuple(sorted(specialties, key=lambda result: result.specialty or "")),
        )
        object.__setattr__(
            self,
            "sub_benchmark_results",
            tuple(
                sorted(
                    sub_benchmarks,
                    key=lambda result: (
                        result.specialty or "",
                        result.sub_benchmark or "",
                    ),
                )
            ),
        )
        _validate_report_rule_bounds(self, self.decision_rule)

    @property
    def verdict(self) -> ParityVerdict:
        return self.overall.verdict

    @property
    def comparison_role(self) -> str:
        if self.track is BenchmarkTrack.REPRESENTATIVE:
            return "primary-terminal"
        return "diagnostic-only"

    @property
    def terminal_verdict(self) -> ParityVerdict | None:
        if self.track is BenchmarkTrack.REPRESENTATIVE:
            return self.overall.verdict
        return None

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "program_hash": self.program_hash,
            "comparison_id": self.comparison_id,
            "registry_hash": self.registry_hash,
            "archetype_hash": self.archetype_hash,
            "evaluation_contract_hash": self.evaluation_contract_hash,
            "benchmark_archetype": self.benchmark_archetype,
            "specialty": self.specialty,
            "track": self.track.value,
            "endpoint": self.endpoint,
            "input_hash": self.input_hash,
            "source_results_hash": self.source_results_hash,
            "run_adapter_receipts_hash": self.run_adapter_receipts_hash,
            "decision_rule_hash": self.decision_rule_hash,
            "decision_rule": self.decision_rule.to_dict(),
            "analysis_code_hash": self.analysis_code_hash,
            "model_panel": [model.to_dict() for model in self.model_panel],
            "bootstrap_algorithm": self.bootstrap_algorithm,
            "bootstrap_seed": self.bootstrap_seed,
            "bootstrap_draws": self.bootstrap_draws,
            "overall": self.overall.to_dict(),
            "specialty_results": [
                result.to_dict() for result in self.specialty_results
            ],
            "sub_benchmark_results": [
                result.to_dict() for result in self.sub_benchmark_results
            ],
            "verdict_scope": self.verdict_scope,
            "comparison_role": self.comparison_role,
            "terminal_verdict": (
                self.terminal_verdict.value
                if self.terminal_verdict is not None
                else None
            ),
            "artifact_hash_kind": self.artifact_hash_kind,
            "verdict": self.verdict.value,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["artifact_hash"] = _digest(payload)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SyntheticParityReport":
        fields = {
            "schema_version",
            "study_id",
            "program_hash",
            "comparison_id",
            "registry_hash",
            "archetype_hash",
            "evaluation_contract_hash",
            "benchmark_archetype",
            "specialty",
            "track",
            "endpoint",
            "input_hash",
            "source_results_hash",
            "run_adapter_receipts_hash",
            "decision_rule_hash",
            "decision_rule",
            "analysis_code_hash",
            "model_panel",
            "bootstrap_algorithm",
            "bootstrap_seed",
            "bootstrap_draws",
            "overall",
            "specialty_results",
            "sub_benchmark_results",
            "verdict_scope",
            "comparison_role",
            "terminal_verdict",
            "artifact_hash_kind",
            "verdict",
            "artifact_hash",
        }
        _fields(data, fields, "synthetic parity report")
        payload = {key: data[key] for key in fields - {"artifact_hash"}}
        if _digest(payload) != data["artifact_hash"]:
            raise ValueError("synthetic parity report artifact hash mismatch")
        result = cls(
            study_id=data["study_id"],
            program_hash=data["program_hash"],
            comparison_id=data["comparison_id"],
            registry_hash=data["registry_hash"],
            archetype_hash=data["archetype_hash"],
            evaluation_contract_hash=data["evaluation_contract_hash"],
            benchmark_archetype=data["benchmark_archetype"],
            specialty=data["specialty"],
            track=data["track"],
            endpoint=data["endpoint"],
            input_hash=data["input_hash"],
            source_results_hash=data["source_results_hash"],
            run_adapter_receipts_hash=data["run_adapter_receipts_hash"],
            decision_rule_hash=data["decision_rule_hash"],
            decision_rule=ParityDecisionRule.from_dict(data["decision_rule"]),
            analysis_code_hash=data["analysis_code_hash"],
            model_panel=tuple(
                ModelIdentity.from_dict(value) for value in data["model_panel"]
            ),
            bootstrap_algorithm=data["bootstrap_algorithm"],
            bootstrap_seed=data["bootstrap_seed"],
            bootstrap_draws=data["bootstrap_draws"],
            overall=ScopeParityResult.from_dict(data["overall"]),
            specialty_results=tuple(
                ScopeParityResult.from_dict(value)
                for value in data["specialty_results"]
            ),
            sub_benchmark_results=tuple(
                ScopeParityResult.from_dict(value)
                for value in data["sub_benchmark_results"]
            ),
            verdict_scope=data["verdict_scope"],
            artifact_hash_kind=data["artifact_hash_kind"],
            schema_version=data["schema_version"],
        )
        if data["verdict"] != result.verdict.value:
            raise ValueError("synthetic parity report verdict was not derived")
        if data["comparison_role"] != result.comparison_role:
            raise ValueError("synthetic parity report role was not derived")
        terminal_verdict = (
            result.terminal_verdict.value
            if result.terminal_verdict is not None
            else None
        )
        if data["terminal_verdict"] != terminal_verdict:
            raise ValueError("synthetic parity report terminal verdict was not derived")
        if result.digest != data["artifact_hash"]:
            raise ValueError("synthetic parity report is not canonical")
        return result

    @classmethod
    def from_json(cls, payload: str) -> "SyntheticParityReport":
        data = strict_json_loads(payload, "synthetic parity report", allow_bytes=True)
        return cls.from_dict(data)

    @property
    def digest(self) -> str:
        return _digest(self._payload())


def _validate_report_rule_bounds(
    report: SyntheticParityReport, rule: ParityDecisionRule
) -> None:
    scopes = (
        report.overall,
        *report.specialty_results,
        *report.sub_benchmark_results,
    )
    expected = {
        "synthetic-minus-real": (
            -rule.per_model_delta_margin,
            rule.per_model_delta_margin,
        ),
        "absolute-difficulty-shift": (
            0.0,
            rule.absolute_difficulty_shift_margin,
        ),
        "spearman-rank-order-agreement": (
            rule.minimum_rank_agreement,
            1.0,
        ),
        "discrimination-spread-ratio": (
            rule.minimum_discrimination_spread_ratio,
            rule.maximum_discrimination_spread_ratio,
        ),
    }
    for scope in scopes:
        if scope.case_family_pairs < rule.minimum_case_family_pairs_per_scope:
            raise ValueError(
                "report scope violates the frozen minimum case-family pair count"
            )
        measures = (
            *(result.delta for result in scope.model_results),
            scope.absolute_difficulty_shift,
            scope.rank_order_agreement,
            scope.discrimination_spread_ratio,
        )
        for measure in measures:
            lower, upper = expected[measure.name]
            if measure.acceptable_lower != lower or measure.acceptable_upper != upper:
                raise ValueError(
                    f"report acceptance bounds for {measure.name!r} do not match "
                    "the frozen decision rule"
                )
            if measure.not_estimable_reason is None:
                assert measure.confidence_interval is not None
                if (
                    measure.confidence_interval.confidence_level
                    != rule.confidence_level
                ):
                    raise ValueError(
                        f"report confidence level for {measure.name!r} does not "
                        "match the frozen decision rule"
                    )
            elif measure.name != "discrimination-spread-ratio":
                raise ValueError(
                    "only the discrimination spread ratio can be non-estimable"
                )


def analyze_synthetic_parity(
    study: SyntheticParityInput,
    rule: ParityDecisionRule,
    *,
    program: SyntheticBenchmarkProgram,
    analysis_code_hash: str,
    allow_source_plan_subset: bool = False,
) -> SyntheticParityReport:
    """Analyze paired case-family clusters under a frozen decision rule."""

    if not isinstance(study, SyntheticParityInput):
        raise ValueError("study must be SyntheticParityInput")
    if not isinstance(rule, ParityDecisionRule):
        raise ValueError("rule must be ParityDecisionRule")
    _hash("analysis_code_hash", analysis_code_hash)
    study.validate_against_program(
        program,
        allow_source_plan_subset=allow_source_plan_subset,
    )
    comparison = program.comparison(study.comparison_id)
    endpoint = program.registry.get(comparison.archetype_id).endpoint(
        comparison.endpoint_id
    )
    if endpoint.margin_unit is MarginUnit.PROFILE_DISTANCE:
        raise ValueError(
            "centered model-profile distance is registered for planning but is "
            "not implemented by the scalar per-model parity analyzer"
        )
    if rule.digest != study.decision_rule_hash:
        raise ValueError("decision rule does not match the program-bound rule hash")
    if not math.isclose(
        rule.per_model_delta_margin,
        comparison.margin.value,
        rel_tol=0.0,
        abs_tol=0.0,
    ):
        raise ValueError(
            "decision rule per-model margin does not match the registered "
            "program comparison margin"
        )

    matrix = _case_matrix(study)
    all_pairs = tuple(pair.pair_id for pair in study.selection.pairs)
    _validate_scope_sizes(study, rule)
    overall = _analyze_scope(
        study,
        rule,
        matrix,
        all_pairs,
        specialty=None,
        sub_benchmark=None,
    )
    specialties = sorted({pair.specialty for pair in study.selection.pairs})
    specialty_results = tuple(
        _analyze_scope(
            study,
            rule,
            matrix,
            tuple(
                pair.pair_id
                for pair in study.selection.pairs
                if pair.specialty == specialty
            ),
            specialty=specialty,
            sub_benchmark=None,
        )
        for specialty in specialties
    )
    subgroup_keys = sorted(
        {(pair.specialty, pair.sub_benchmark) for pair in study.selection.pairs}
    )
    sub_benchmark_results = tuple(
        _analyze_scope(
            study,
            rule,
            matrix,
            tuple(
                pair.pair_id
                for pair in study.selection.pairs
                if pair.specialty == specialty and pair.sub_benchmark == sub_benchmark
            ),
            specialty=specialty,
            sub_benchmark=sub_benchmark,
        )
        for specialty, sub_benchmark in subgroup_keys
    )
    return SyntheticParityReport(
        study_id=study.study_id,
        program_hash=study.program_hash,
        comparison_id=study.comparison_id,
        registry_hash=study.registry_hash,
        archetype_hash=study.archetype_hash,
        evaluation_contract_hash=study.evaluation_contract_hash,
        benchmark_archetype=study.benchmark_archetype,
        specialty=study.specialty,
        track=study.track,
        endpoint=study.endpoint,
        input_hash=study.digest,
        source_results_hash=study.source_results_hash,
        run_adapter_receipts_hash=study.run_adapter_receipts_hash,
        decision_rule_hash=rule.digest,
        decision_rule=rule,
        analysis_code_hash=analysis_code_hash,
        model_panel=study.model_panel,
        bootstrap_algorithm=BOOTSTRAP_ALGORITHM,
        bootstrap_seed=rule.bootstrap_seed,
        bootstrap_draws=rule.bootstrap_draws,
        overall=overall,
        specialty_results=specialty_results,
        sub_benchmark_results=sub_benchmark_results,
        verdict_scope=(
            REPRESENTATIVE_VERDICT_SCOPE
            if study.track is BenchmarkTrack.REPRESENTATIVE
            else STRESS_VERDICT_SCOPE
        ),
    )


def replay_synthetic_parity_report(
    study: SyntheticParityInput,
    report: SyntheticParityReport,
    *,
    program: SyntheticBenchmarkProgram,
    allow_source_plan_subset: bool = False,
) -> SyntheticParityReport:
    """Recompute a report from its pinned input and embedded decision rule."""

    if not isinstance(report, SyntheticParityReport):
        raise ValueError("report must be a SyntheticParityReport")
    replayed = analyze_synthetic_parity(
        study,
        report.decision_rule,
        program=program,
        analysis_code_hash=report.analysis_code_hash,
        allow_source_plan_subset=allow_source_plan_subset,
    )
    if replayed.to_dict() != report.to_dict():
        raise ValueError(
            "synthetic parity report is not exactly derived from its pinned input"
        )
    return replayed


def validate_synthetic_selection_inventory(
    study: SyntheticParityInput,
    inventory: SpecialtyCellInventory,
    *,
    program: SyntheticBenchmarkProgram | None = None,
    require_exact_families: bool = True,
) -> None:
    """Verify evaluated synthetic families and variants against an inventory.

    Exact matching is the default for comparison-level lab artifacts. A
    preregistered optimization split may select a strict subset of one
    program-bound full-corpus inventory.
    """

    if not isinstance(study, SyntheticParityInput):
        raise ValueError("study must be a SyntheticParityInput")
    if not isinstance(inventory, SpecialtyCellInventory):
        raise ValueError("inventory must be a SpecialtyCellInventory")
    if not isinstance(require_exact_families, bool):
        raise ValueError("require_exact_families must be boolean")
    if program is not None and not isinstance(program, SyntheticBenchmarkProgram):
        raise ValueError("program must be a SyntheticBenchmarkProgram")
    if not require_exact_families:
        if program is None:
            raise ValueError(
                "subset selection requires the exact program-bound inventory"
            )
        comparison = program.comparison(study.comparison_id)
        source_binding = comparison.source_plan_binding
        if (
            source_binding is None
            or inventory.inventory_sha256 != source_binding.cell_inventory_sha256
        ):
            raise ValueError(
                "synthetic inventory does not match the program source binding"
            )
    if study.specialty != inventory.specialty.value:
        raise ValueError(
            "parity input specialty does not match the specialty cell inventory"
        )
    if study.track is not inventory.track:
        raise ValueError(
            "parity input track does not match the specialty cell inventory"
        )
    synthetic_arm = next(
        (arm for arm in study.arms if arm.role is ArmRole.SYNTHETIC),
        None,
    )
    if (
        synthetic_arm is None
        or synthetic_arm.content_hash != inventory.export_bundle_sha256
    ):
        raise ValueError(
            "parity input synthetic arm does not match the inventory bundle"
        )

    families = {
        family.family_id: (cell.cell_id, family)
        for cell in inventory.cells
        for family in cell.families
    }
    selected_ids = {pair.synthetic_case_family_id for pair in study.selection.pairs}
    inventory_ids = set(families)
    if require_exact_families and selected_ids != inventory_ids:
        missing = sorted(set(families) - selected_ids)
        extra = sorted(selected_ids - set(families))
        raise ValueError(
            "parity input synthetic families do not exactly match the inventory: "
            f"missing={missing}, extra={extra}"
        )
    if not require_exact_families and not selected_ids <= inventory_ids:
        extra = sorted(selected_ids - inventory_ids)
        raise ValueError(
            "parity input synthetic families are outside the program inventory: "
            f"{extra}"
        )

    for pair in study.selection.pairs:
        cell_id, family = families[pair.synthetic_case_family_id]
        if pair.plan_cell_id != cell_id:
            raise ValueError(
                f"synthetic family {pair.synthetic_case_family_id!r} is assigned "
                "to a different inventory plan cell"
            )
        authored_ids = set(family.authored_item_ids)
        selected_variant_ids = {
            slot.synthetic_variant_id for slot in pair.variant_slots
        }
        if not selected_variant_ids <= authored_ids:
            unknown = sorted(selected_variant_ids - authored_ids)
            raise ValueError(
                f"synthetic family {pair.synthetic_case_family_id!r} selects "
                f"variants outside the inventory: {unknown}"
            )
        baseline_slots = tuple(
            slot for slot in pair.variant_slots if slot.kind is VariantSlotKind.BASELINE
        )
        if (
            len(baseline_slots) != 1
            or baseline_slots[0].synthetic_variant_id != family.family_id
        ):
            raise ValueError(
                f"synthetic family {pair.synthetic_case_family_id!r} does not "
                "select its inventoried baseline in the baseline slot"
            )


def validate_reference_selection_inventory(
    study: SyntheticParityInput,
    inventory: ReferenceSelectionInventory,
    *,
    program: SyntheticBenchmarkProgram,
    require_exact_families: bool = True,
) -> None:
    """Verify evaluated reference families and variants against its inventory.

    Exact matching is the default. A preregistered optimization split may
    select a strict subset of the exact full-corpus inventory bound by the
    candidate program.
    """

    if not isinstance(study, SyntheticParityInput):
        raise ValueError("study must be a SyntheticParityInput")
    if not isinstance(inventory, ReferenceSelectionInventory):
        raise ValueError("inventory must be a ReferenceSelectionInventory")
    if not isinstance(program, SyntheticBenchmarkProgram):
        raise ValueError("program must be a SyntheticBenchmarkProgram")
    if not isinstance(require_exact_families, bool):
        raise ValueError("require_exact_families must be boolean")
    comparison = program.comparison(study.comparison_id)
    if inventory.inventory_sha256 != comparison.reference.manifest_hash:
        raise ValueError(
            "reference selection inventory does not match the program manifest"
        )
    if inventory.bundle_sha256 != comparison.reference.bundle_hash:
        raise ValueError(
            "reference selection inventory does not match the program bundle"
        )
    if inventory.source_revision != comparison.reference.source_revision:
        raise ValueError(
            "reference selection inventory source revision does not match the program"
        )
    if (
        inventory.selection_protocol_sha256 != study.selection.protocol_hash
        or inventory.selection_commit_sha256 != study.selection.selection_commit_hash
    ):
        raise ValueError(
            "reference selection inventory does not match the frozen selection"
        )
    real_arm = next((arm for arm in study.arms if arm.role is ArmRole.REAL), None)
    if (
        real_arm is None
        or real_arm.content_hash != inventory.bundle_sha256
        or real_arm.source_revision != inventory.source_revision
    ):
        raise ValueError(
            "parity input reference arm does not match the reference inventory"
        )

    families = {family.family_id: family for family in inventory.families}
    selected_ids = {pair.real_case_family_id for pair in study.selection.pairs}
    inventory_ids = set(families)
    if require_exact_families and selected_ids != inventory_ids:
        missing = sorted(set(families) - selected_ids)
        extra = sorted(selected_ids - set(families))
        raise ValueError(
            "parity input reference families do not exactly match the inventory: "
            f"missing={missing}, extra={extra}"
        )
    if not require_exact_families and not selected_ids <= inventory_ids:
        extra = sorted(selected_ids - inventory_ids)
        raise ValueError(
            "parity input reference families are outside the program inventory: "
            f"{extra}"
        )
    for pair in study.selection.pairs:
        family = families[pair.real_case_family_id]
        selected_variant_ids = {slot.real_variant_id for slot in pair.variant_slots}
        if not selected_variant_ids <= set(family.item_ids):
            unknown = sorted(selected_variant_ids - set(family.item_ids))
            raise ValueError(
                f"reference family {pair.real_case_family_id!r} selects variants "
                f"outside the inventory: {unknown}"
            )
        baseline_slots = tuple(
            slot for slot in pair.variant_slots if slot.kind is VariantSlotKind.BASELINE
        )
        if baseline_slots and (
            len(baseline_slots) != 1
            or baseline_slots[0].real_variant_id != family.baseline_item_id
        ):
            raise ValueError(
                f"reference family {pair.real_case_family_id!r} does not select "
                "its inventoried baseline in the baseline slot"
            )


def validate_cross_arm_content_isolation(
    reference_inventory: ReferenceSelectionInventory,
    synthetic_inventory: SpecialtyCellInventory,
) -> None:
    """Reject exact reference-content copies hidden behind synthetic IDs.

    Call this together with the two selection-membership validators. Those
    validators prove that the inventories are the exact evaluated selections;
    this validator proves that their ID-independent canonical content is
    disjoint.
    """

    if not isinstance(reference_inventory, ReferenceSelectionInventory):
        raise ValueError("reference_inventory must be a ReferenceSelectionInventory")
    if not isinstance(synthetic_inventory, SpecialtyCellInventory):
        raise ValueError("synthetic_inventory must be a SpecialtyCellInventory")
    if (
        reference_inventory.content_hashing_contract_sha256
        != synthetic_inventory.content_hashing_contract_sha256
    ):
        raise ValueError(
            "reference and synthetic inventories use different canonical "
            "content hashing contracts"
        )

    reference_family_hashes = {
        family.family_content_sha256 for family in reference_inventory.families
    }
    synthetic_families = tuple(
        family for cell in synthetic_inventory.cells for family in cell.families
    )
    synthetic_family_hashes = {
        family.canonical_content_sha256 for family in synthetic_families
    }
    overlapping_family_hashes = sorted(
        reference_family_hashes & synthetic_family_hashes
    )
    if overlapping_family_hashes:
        raise ValueError(
            "reference and synthetic inventories overlap on canonical family "
            f"content hashes: {overlapping_family_hashes}"
        )

    reference_item_hashes = {
        item.content_sha256
        for family in reference_inventory.families
        for item in family.items
    }
    synthetic_item_hashes = {
        item.canonical_content_sha256
        for family in synthetic_families
        for item in family.authored_items
    }
    overlapping_item_hashes = sorted(reference_item_hashes & synthetic_item_hashes)
    if overlapping_item_hashes:
        raise ValueError(
            "reference and synthetic inventories overlap on canonical item "
            f"content hashes: {overlapping_item_hashes}"
        )


def _validate_scope_sizes(
    study: SyntheticParityInput, rule: ParityDecisionRule
) -> None:
    scopes: list[tuple[str, int]] = [
        ("overall", len(study.selection.pairs)),
    ]
    specialties = sorted({pair.specialty for pair in study.selection.pairs})
    scopes.extend(
        (
            f"specialty/{specialty}",
            sum(pair.specialty == specialty for pair in study.selection.pairs),
        )
        for specialty in specialties
    )
    subgroup_keys = sorted(
        {(pair.specialty, pair.sub_benchmark) for pair in study.selection.pairs}
    )
    scopes.extend(
        (
            f"sub-benchmark/{specialty}/{sub_benchmark}",
            sum(
                pair.specialty == specialty and pair.sub_benchmark == sub_benchmark
                for pair in study.selection.pairs
            ),
        )
        for specialty, sub_benchmark in subgroup_keys
    )
    minimum = rule.minimum_case_family_pairs_per_scope
    undersized = [(label, count) for label, count in scopes if count < minimum]
    if undersized:
        label, count = undersized[0]
        raise ValueError(
            f"parity scope {label!r} has {count} case-family pairs; "
            f"the preregistered minimum is {minimum}"
        )


def _case_matrix(
    study: SyntheticParityInput,
) -> dict[str, dict[ArmRole, dict[str, float]]]:
    pair_by_case: dict[tuple[ArmRole, str], str] = {}
    for pair in study.selection.pairs:
        for role in ArmRole:
            pair_by_case[(role, pair.case_family_id(role))] = pair.pair_id
    trials: dict[tuple[str, ArmRole, str], list[float]] = {}
    for observation in study.observations:
        pair_id = pair_by_case[(observation.arm_role, observation.case_family_id)]
        key = (pair_id, observation.arm_role, observation.model_id)
        trials.setdefault(key, []).append(observation.value)
    matrix: dict[str, dict[ArmRole, dict[str, float]]] = {
        pair.pair_id: {role: {} for role in ArmRole} for pair in study.selection.pairs
    }
    for (pair_id, role, model_id), values in trials.items():
        matrix[pair_id][role][model_id] = fmean(values)
    return matrix


def _analyze_scope(
    study: SyntheticParityInput,
    rule: ParityDecisionRule,
    matrix: Mapping[str, Mapping[ArmRole, Mapping[str, float]]],
    pair_ids: tuple[str, ...],
    *,
    specialty: str | None,
    sub_benchmark: str | None,
) -> ScopeParityResult:
    if not pair_ids:
        raise ValueError("parity scope cannot be empty")
    pair_ids = tuple(sorted(pair_ids))
    model_ids = tuple(model.model_id for model in study.model_panel)
    point_real = _arm_scores(matrix, pair_ids, ArmRole.REAL, model_ids)
    point_synthetic = _arm_scores(matrix, pair_ids, ArmRole.SYNTHETIC, model_ids)
    point_rank = _rank_agreement_or_zero(point_real, point_synthetic)
    point_spread = _spread_ratio(point_real, point_synthetic)
    point_difficulty = abs(fmean(point_synthetic.values()) - fmean(point_real.values()))

    rng = random.Random(_scope_seed(rule.bootstrap_seed, specialty, sub_benchmark))
    delta_draws = {model_id: [] for model_id in model_ids}
    difficulty_draws: list[float] = []
    rank_draws: list[float] = []
    spread_draws: list[float | None] = []
    draws_hasher = hashlib.sha256()
    for _ in range(rule.bootstrap_draws):
        sampled = tuple(pair_ids[rng.randrange(len(pair_ids))] for _ in pair_ids)
        draws_hasher.update(_canonical_json(sampled).encode("utf-8"))
        draws_hasher.update(b"\n")
        real_scores = _arm_scores(matrix, sampled, ArmRole.REAL, model_ids)
        synthetic_scores = _arm_scores(matrix, sampled, ArmRole.SYNTHETIC, model_ids)
        for model_id in model_ids:
            delta_draws[model_id].append(
                synthetic_scores[model_id] - real_scores[model_id]
            )
        difficulty_draws.append(
            abs(fmean(synthetic_scores.values()) - fmean(real_scores.values()))
        )
        rank_draws.append(_rank_agreement_or_zero(real_scores, synthetic_scores))
        spread_draws.append(_spread_ratio(real_scores, synthetic_scores))

    model_by_id = {model.model_id: model for model in study.model_panel}
    model_results = tuple(
        ModelParityResult(
            model_id=model_id,
            model_family=model_by_id[model_id].model_family,
            real_score=point_real[model_id],
            synthetic_score=point_synthetic[model_id],
            delta=_measure(
                "synthetic-minus-real",
                point_synthetic[model_id] - point_real[model_id],
                delta_draws[model_id],
                rule,
                -rule.per_model_delta_margin,
                rule.per_model_delta_margin,
            ),
        )
        for model_id in model_ids
    )
    return ScopeParityResult(
        specialty=specialty,
        sub_benchmark=sub_benchmark,
        case_family_pairs=len(pair_ids),
        model_results=model_results,
        absolute_difficulty_shift=_measure(
            "absolute-difficulty-shift",
            point_difficulty,
            difficulty_draws,
            rule,
            0.0,
            rule.absolute_difficulty_shift_margin,
        ),
        rank_order_agreement=_measure(
            "spearman-rank-order-agreement",
            point_rank,
            rank_draws,
            rule,
            rule.minimum_rank_agreement,
            1.0,
        ),
        discrimination_spread_ratio=_spread_measure(
            point_spread,
            spread_draws,
            rule,
        ),
        cluster_manifest_hash=_digest(
            [
                pair.to_dict()
                for pair in study.selection.pairs
                if pair.pair_id in set(pair_ids)
            ]
        ),
        bootstrap_draws_hash=draws_hasher.hexdigest(),
    )


def _measure(
    name: str,
    estimate: float,
    draws: Sequence[float],
    rule: ParityDecisionRule,
    acceptable_lower: float,
    acceptable_upper: float,
) -> EquivalenceMeasure:
    lower, upper = _percentile_interval(draws, rule.confidence_level, estimate)
    return EquivalenceMeasure(
        name=name,
        estimate=estimate,
        confidence_interval=ConfidenceInterval(
            lower=lower,
            upper=upper,
            confidence_level=rule.confidence_level,
        ),
        acceptable_lower=acceptable_lower,
        acceptable_upper=acceptable_upper,
    )


def _spread_measure(
    estimate: float | None,
    draws: Sequence[float | None],
    rule: ParityDecisionRule,
) -> EquivalenceMeasure:
    if estimate is None:
        reason = "real-arm-zero-model-spread-at-point-estimate"
    else:
        non_estimable_draws = sum(draw is None for draw in draws)
        reason = (
            "real-arm-zero-model-spread-in-bootstrap-resample:"
            f"{non_estimable_draws}-of-{len(draws)}"
            if non_estimable_draws
            else None
        )
    if reason is not None:
        return EquivalenceMeasure(
            name="discrimination-spread-ratio",
            estimate=None,
            confidence_interval=None,
            acceptable_lower=rule.minimum_discrimination_spread_ratio,
            acceptable_upper=rule.maximum_discrimination_spread_ratio,
            not_estimable_reason=reason,
        )
    return _measure(
        "discrimination-spread-ratio",
        estimate,
        [draw for draw in draws if draw is not None],
        rule,
        rule.minimum_discrimination_spread_ratio,
        rule.maximum_discrimination_spread_ratio,
    )


def _arm_scores(
    matrix: Mapping[str, Mapping[ArmRole, Mapping[str, float]]],
    pair_ids: Sequence[str],
    role: ArmRole,
    model_ids: Sequence[str],
) -> dict[str, float]:
    return {
        model_id: fmean(matrix[pair_id][role][model_id] for pair_id in pair_ids)
        for model_id in model_ids
    }


def _spread_ratio(
    real_scores: Mapping[str, float], synthetic_scores: Mapping[str, float]
) -> float | None:
    real_spread = max(real_scores.values()) - min(real_scores.values())
    if math.isclose(real_spread, 0.0, rel_tol=0.0, abs_tol=1e-15):
        return None
    synthetic_spread = max(synthetic_scores.values()) - min(synthetic_scores.values())
    return synthetic_spread / real_spread


def _rank_agreement_or_zero(
    real_scores: Mapping[str, float],
    synthetic_scores: Mapping[str, float],
) -> float:
    try:
        return spearman_rank_agreement(real_scores, synthetic_scores)
    except ValueError as exc:
        if "all-tied arm" not in str(exc):
            raise
        # A scope or resample that erases all between-model discrimination
        # cannot support rank preservation. Zero is the conservative finite
        # value; the spread-ratio endpoint independently records the collapse.
        return 0.0


def _percentile_interval(
    draws: Sequence[float], confidence: float, point_estimate: float
) -> tuple[float, float]:
    if not draws:
        raise ValueError("bootstrap draws cannot be empty")
    finite = [_finite("bootstrap draw", draw) for draw in draws]
    return percentile_interval(finite, confidence, point_estimate, quantile_fn=_quantile)


def _quantile(ordered: Sequence[float], probability: float) -> float:
    return ordered[0] if len(ordered) == 1 else quantile(ordered, probability, weighted=True)


def _scope_seed(seed: int, specialty: str | None, sub_benchmark: str | None) -> int:
    payload = _canonical_json(
        {
            "seed": seed,
            "specialty": specialty,
            "sub_benchmark": sub_benchmark,
            "algorithm": BOOTSTRAP_ALGORITHM,
        }
    )
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16], 16)


def _combine_verdicts(verdicts: Sequence[ParityVerdict]) -> ParityVerdict:
    if any(verdict is ParityVerdict.NON_EQUIVALENT for verdict in verdicts):
        return ParityVerdict.NON_EQUIVALENT
    if all(verdict is ParityVerdict.EQUIVALENT for verdict in verdicts):
        return ParityVerdict.EQUIVALENT
    return ParityVerdict.INCONCLUSIVE


def _observation_key(
    observation: EndpointObservation,
) -> tuple[str, str, str, str, str, str, str, str, int]:
    return (
        observation.arm_role.value,
        observation.specialty,
        observation.sub_benchmark,
        observation.case_family_id,
        observation.variant_slot_id,
        observation.variant_id,
        observation.model_id,
        observation.model_family,
        observation.trial,
    )


def _normalize_field(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _enum(enum_type: type[Enum], value: Any, name: str) -> Any:
    return enum_member(value, enum_type, name)


def _text(name: str, value: Any) -> str:
    return text(value, name)


def _hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


def _finite(name: str, value: Any) -> float:
    return number(value, name)


def _fields(data: Mapping[str, Any], expected: set[str], name: str) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    actual = set(data)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        parts = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if extra:
            parts.append("unexpected " + ", ".join(extra))
        raise ValueError(f"{name} fields are invalid: {'; '.join(parts)}")


__all__ = [
    "ArmRole",
    "BenchmarkArm",
    "BOOTSTRAP_ALGORITHM",
    "ConfidenceInterval",
    "EndpointObservation",
    "EquivalenceMeasure",
    "INPUT_SCHEMA_VERSION",
    "ModelIdentity",
    "ModelParityResult",
    "ParityDecisionRule",
    "ParityVerdict",
    "REPORT_SCHEMA_VERSION",
    "REPRESENTATIVE_VERDICT_SCOPE",
    "RUN_ADAPTER_RECEIPT_SCHEMA_VERSION",
    "RUN_EVIDENCE_SCHEMA_VERSION",
    "RUN_MANIFEST_ADAPTER_CODE_HASH_KEY",
    "RUN_MANIFEST_EVALUATION_CONTRACT_HASH_KEY",
    "RUN_MANIFEST_EXPECTED_PROVIDER_IDENTITY_KEY",
    "RUN_MANIFEST_ROUTE_FAMILY_KEY",
    "RUN_MANIFEST_ROUTE_SNAPSHOT_KEY",
    "RUN_MANIFEST_RUNTIME_CONFIG_HASH_KEY",
    "RUN_MANIFEST_SELECTION_HASH_KEY",
    "RUN_MANIFEST_SELECTION_PROTOCOL_HASH_KEY",
    "RULE_SCHEMA_VERSION",
    "ScopeParityResult",
    "SelectionBasis",
    "SelectionManifest",
    "SelectionPair",
    "SOLVER_OBSERVATION_SUBSET_HASH_ALGORITHM",
    "SolverRunAdapterReceipt",
    "SolverRunEvidence",
    "SyntheticParityInput",
    "SyntheticParityReport",
    "STRESS_VERDICT_SCOPE",
    "VariantSlot",
    "VariantSlotKind",
    "VERDICT_SCOPE",
    "analyze_synthetic_parity",
    "canonical_solver_observation_subset_sha256",
    "replay_synthetic_parity_report",
    "spearman_rank_agreement",
    "validate_cross_arm_content_isolation",
    "validate_reference_selection_inventory",
    "validate_synthetic_selection_inventory",
]

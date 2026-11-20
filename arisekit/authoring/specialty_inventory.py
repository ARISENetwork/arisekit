"""Bind reviewed specialty case families to exact allocation-plan cells.

The inventory is a provenance contract, not a classifier.  A caller supplies
the family-to-cell assignment explicitly.  The implementation never examines
model outputs, scores, parity results, or other outcome data to choose a cell.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from arisekit.authoring.blueprint import BenchmarkBlueprint, CaseFamily
from arisekit.common.hashing import canonical_sha256 as _digest
from arisekit.common.jsonio import strict_json_object
from arisekit.common.records import CanonicalPropertyRecord
from arisekit.common.validate import (
    exact_fields as _fields,
    integer as _integer,
    positive_int as _positive_int,
    sha256_hex as _hash,
    text as _text,
)
from arisekit.authoring.content_inventory import (
    CANONICAL_CONTENT_HASHING_CONTRACT_SHA256,
    canonical_family_content_sha256,
    canonical_item_content_sha256,
)
from arisekit.authoring.specialty import (
    CANONICAL_ACUITY_LEVELS,
    AcuityAllocation,
    AcuityLevel,
    BenchmarkArchetype,
    BenchmarkTrack,
    ConditionAllocation,
    ConditionFamily,
    Specialty,
    SpecialtyBenchmarkPlan,
    SubBenchmarkCell,
    normalize_condition_family,
    normalize_specialty,
)


SPECIALTY_CELL_INVENTORY_SCHEMA_VERSION = "arisekit.specialty-cell-inventory.v3"
ALLOCATION_BASIS = "explicit-reviewed-family-to-plan-cell-mapping"


@dataclass(frozen=True, slots=True)
class AuthoredItemBinding:
    """One authored item bound to ID-independent canonical presentation content."""

    item_id: str
    canonical_content_sha256: str

    def __post_init__(self) -> None:
        _text(self.item_id, "authored item id")
        _hash(self.canonical_content_sha256, "canonical_content_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "item_id": self.item_id,
            "canonical_content_sha256": self.canonical_content_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuthoredItemBinding":
        _fields(
            data,
            {"item_id", "canonical_content_sha256"},
            "authored item binding",
        )
        result = cls(
            item_id=_string(data["item_id"], "authored item id"),
            canonical_content_sha256=_string(
                data["canonical_content_sha256"],
                "authored item canonical content SHA-256",
            ),
        )
        if dict(data) != result.to_dict():
            raise ValueError("authored item binding is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class AuthoredFamilyBinding:
    """Exact reviewed content assigned to one plan cell."""

    family_id: str
    case_family_sha256: str
    canonical_content_sha256: str
    workflow_revision: str
    base_specialty: Specialty | str
    condition_family: ConditionFamily | str
    acuity: AcuityLevel | str
    authored_items: tuple[AuthoredItemBinding, ...]

    def __post_init__(self) -> None:
        _text(self.family_id, "family_id")
        _hash(self.case_family_sha256, "case_family_sha256")
        _hash(self.canonical_content_sha256, "canonical_content_sha256")
        _hash(self.workflow_revision, "workflow_revision")
        object.__setattr__(
            self,
            "base_specialty",
            normalize_specialty(self.base_specialty),
        )
        object.__setattr__(
            self,
            "condition_family",
            normalize_condition_family(self.condition_family),
        )
        object.__setattr__(self, "acuity", AcuityLevel(self.acuity))
        items = tuple(self.authored_items)
        if not items or any(
            not isinstance(item, AuthoredItemBinding) for item in items
        ):
            raise ValueError("authored_items must contain AuthoredItemBinding records")
        item_ids = tuple(item.item_id for item in items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("authored item IDs must be unique")
        if item_ids[0] != self.family_id:
            raise ValueError("the baseline authored item must equal family_id")
        item_hashes = tuple(item.canonical_content_sha256 for item in items)
        if len(item_hashes) != len(set(item_hashes)):
            raise ValueError("authored item canonical content hashes must be unique")
        if self.canonical_content_sha256 != canonical_family_content_sha256(
            item_hashes
        ):
            raise ValueError(
                "family canonical content hash must be derived from authored items"
            )
        object.__setattr__(self, "authored_items", items)

    @property
    def authored_item_ids(self) -> tuple[str, ...]:
        return tuple(item.item_id for item in self.authored_items)

    @property
    def authored_variant_count(self) -> int:
        return len(self.authored_item_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "case_family_sha256": self.case_family_sha256,
            "canonical_content_sha256": self.canonical_content_sha256,
            "workflow_revision": self.workflow_revision,
            "base_specialty": Specialty(self.base_specialty).value,
            "condition_family": ConditionFamily(self.condition_family).value,
            "acuity": AcuityLevel(self.acuity).value,
            "authored_items": [item.to_dict() for item in self.authored_items],
            "authored_item_ids": list(self.authored_item_ids),
            "authored_variant_count": self.authored_variant_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuthoredFamilyBinding":
        _fields(
            data,
            {
                "family_id",
                "case_family_sha256",
                "canonical_content_sha256",
                "workflow_revision",
                "base_specialty",
                "condition_family",
                "acuity",
                "authored_items",
                "authored_item_ids",
                "authored_variant_count",
            },
            "authored family binding",
        )
        result = cls(
            family_id=_string(data["family_id"], "family_id"),
            case_family_sha256=_string(
                data["case_family_sha256"], "case_family_sha256"
            ),
            canonical_content_sha256=_string(
                data["canonical_content_sha256"],
                "canonical_content_sha256",
            ),
            workflow_revision=_string(data["workflow_revision"], "workflow_revision"),
            base_specialty=_string(data["base_specialty"], "base_specialty"),
            condition_family=_string(
                data["condition_family"],
                "condition_family",
            ),
            acuity=_string(data["acuity"], "acuity"),
            authored_items=tuple(
                AuthoredItemBinding.from_dict(item)
                for item in _mapping_tuple(
                    data["authored_items"],
                    "authored_items",
                )
            ),
        )
        if list(result.authored_item_ids) != data["authored_item_ids"]:
            raise ValueError("authored item IDs are not derived correctly")
        if data["authored_variant_count"] != result.authored_variant_count:
            raise ValueError("authored family variant count is not derived correctly")
        if dict(data) != result.to_dict():
            raise ValueError("authored family binding is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class SpecialtyCellBinding:
    """Materialized content for one exact specialty-plan cell."""

    cell_id: str
    cell_sha256: str
    specialty: Specialty | str
    track: BenchmarkTrack | str
    expected_family_count: int
    authored_variants_per_family: int
    condition_allocations: tuple[ConditionAllocation, ...]
    acuity_allocations: tuple[AcuityAllocation, ...]
    families: tuple[AuthoredFamilyBinding, ...]

    def __post_init__(self) -> None:
        _text(self.cell_id, "cell_id")
        _hash(self.cell_sha256, "cell_sha256")
        object.__setattr__(
            self,
            "specialty",
            normalize_specialty(self.specialty),
        )
        object.__setattr__(self, "track", BenchmarkTrack(self.track))
        _positive_int(self.expected_family_count, "expected_family_count")
        _positive_int(
            self.authored_variants_per_family,
            "authored_variants_per_family",
        )
        condition_allocations = tuple(self.condition_allocations)
        if not condition_allocations or any(
            not isinstance(item, ConditionAllocation) for item in condition_allocations
        ):
            raise ValueError(
                "cell condition_allocations must contain ConditionAllocation records"
            )
        condition_ids = tuple(item.condition_family for item in condition_allocations)
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("cell condition allocations must be unique")
        if sum(item.family_count for item in condition_allocations) != (
            self.expected_family_count
        ):
            raise ValueError(
                "cell condition allocations must sum to expected_family_count"
            )
        object.__setattr__(
            self,
            "condition_allocations",
            condition_allocations,
        )

        acuity_allocations = tuple(self.acuity_allocations)
        if any(not isinstance(item, AcuityAllocation) for item in acuity_allocations):
            raise ValueError(
                "cell acuity_allocations must contain AcuityAllocation records"
            )
        if tuple(item.acuity for item in acuity_allocations) != (
            CANONICAL_ACUITY_LEVELS
        ):
            raise ValueError("cell acuity allocations must use canonical acuity order")
        if sum(item.family_count for item in acuity_allocations) != (
            self.expected_family_count
        ):
            raise ValueError(
                "cell acuity allocations must sum to expected_family_count"
            )
        object.__setattr__(self, "acuity_allocations", acuity_allocations)

        families = tuple(self.families)
        if any(not isinstance(item, AuthoredFamilyBinding) for item in families):
            raise ValueError("cell families must contain AuthoredFamilyBinding records")
        if len(families) != self.expected_family_count:
            raise ValueError(
                f"cell {self.cell_id!r} requires exactly "
                f"{self.expected_family_count} case families"
            )
        family_ids = tuple(item.family_id for item in families)
        if family_ids != tuple(sorted(family_ids)):
            raise ValueError("cell family bindings must use canonical family-id order")
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("cell family IDs must be unique")
        if any(item.base_specialty is not self.specialty for item in families):
            raise ValueError("cell family specialties must match the cell specialty")
        if any(
            item.authored_variant_count != self.authored_variants_per_family
            for item in families
        ):
            raise ValueError(
                "every family must have the cell's exact authored topology"
            )
        expected_condition_histogram = {
            item.condition_family: item.family_count for item in condition_allocations
        }
        actual_condition_histogram = Counter(item.condition_family for item in families)
        if dict(actual_condition_histogram) != expected_condition_histogram:
            raise ValueError(
                "family condition assignments must equal the plan cell "
                "condition allocation"
            )
        expected_acuity_histogram = {
            item.acuity: item.family_count for item in acuity_allocations
        }
        actual_acuity_histogram = Counter(item.acuity for item in families)
        actual_acuity_histogram = {
            level: actual_acuity_histogram.get(level, 0)
            for level in CANONICAL_ACUITY_LEVELS
        }
        if actual_acuity_histogram != expected_acuity_histogram:
            raise ValueError(
                "family acuity assignments must equal the plan cell "
                "acuity allocation"
            )
        expected_prefix = f"{Specialty(self.specialty).value}--{self.track.value}--"
        if not self.cell_id.startswith(expected_prefix):
            raise ValueError("cell_id does not match the bound specialty and track")
        object.__setattr__(self, "families", families)

    @property
    def family_ids(self) -> tuple[str, ...]:
        return tuple(item.family_id for item in self.families)

    @property
    def authored_variant_count(self) -> int:
        return self.expected_family_count * self.authored_variants_per_family

    @property
    def condition_family_histogram(self) -> dict[str, int]:
        return {
            item.condition_family.value: item.family_count
            for item in self.condition_allocations
        }

    @property
    def acuity_histogram(self) -> dict[str, int]:
        return {
            item.acuity.value: item.family_count for item in self.acuity_allocations
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "cell_sha256": self.cell_sha256,
            "specialty": Specialty(self.specialty).value,
            "track": BenchmarkTrack(self.track).value,
            "expected_family_count": self.expected_family_count,
            "authored_variants_per_family": self.authored_variants_per_family,
            "condition_allocations": [
                item.to_dict() for item in self.condition_allocations
            ],
            "acuity_allocations": [item.to_dict() for item in self.acuity_allocations],
            "families": [item.to_dict() for item in self.families],
            "family_ids": list(self.family_ids),
            "authored_variant_count": self.authored_variant_count,
            "condition_family_histogram": self.condition_family_histogram,
            "acuity_histogram": self.acuity_histogram,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialtyCellBinding":
        _fields(
            data,
            {
                "cell_id",
                "cell_sha256",
                "specialty",
                "track",
                "expected_family_count",
                "authored_variants_per_family",
                "condition_allocations",
                "acuity_allocations",
                "families",
                "family_ids",
                "authored_variant_count",
                "condition_family_histogram",
                "acuity_histogram",
            },
            "specialty cell binding",
        )
        families = tuple(
            AuthoredFamilyBinding.from_dict(item)
            for item in _mapping_tuple(data["families"], "families")
        )
        result = cls(
            cell_id=_string(data["cell_id"], "cell_id"),
            cell_sha256=_string(data["cell_sha256"], "cell_sha256"),
            specialty=_string(data["specialty"], "specialty"),
            track=_string(data["track"], "track"),
            expected_family_count=_integer(
                data["expected_family_count"], "expected_family_count"
            ),
            authored_variants_per_family=_integer(
                data["authored_variants_per_family"],
                "authored_variants_per_family",
            ),
            condition_allocations=tuple(
                ConditionAllocation.from_dict(item)
                for item in _mapping_tuple(
                    data["condition_allocations"],
                    "condition_allocations",
                )
            ),
            acuity_allocations=tuple(
                AcuityAllocation.from_dict(item)
                for item in _mapping_tuple(
                    data["acuity_allocations"],
                    "acuity_allocations",
                )
            ),
            families=families,
        )
        if list(result.family_ids) != data["family_ids"]:
            raise ValueError("cell family_ids are not derived correctly")
        if result.authored_variant_count != data["authored_variant_count"]:
            raise ValueError("cell authored_variant_count is not derived correctly")
        if result.condition_family_histogram != data["condition_family_histogram"]:
            raise ValueError("cell condition_family_histogram is not derived correctly")
        if result.acuity_histogram != data["acuity_histogram"]:
            raise ValueError("cell acuity_histogram is not derived correctly")
        if dict(data) != result.to_dict():
            raise ValueError("specialty cell binding is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class SpecialtyCellInventory(CanonicalPropertyRecord):
    """Versioned manifest joining one reviewed export to one plan slice."""

    allocator_archetype_id: BenchmarkArchetype | str
    specialty: Specialty | str
    track: BenchmarkTrack | str
    spec_sha256: str
    plan_sha256: str
    blueprint_id: str
    blueprint_version: str
    blueprint_schema_version: str
    blueprint_sha256: str
    blueprint_authoring_revision: str
    blueprint_workflow_locked_revision: str
    export_manifest_sha256: str
    export_bundle_sha256: str
    exported_case_family_ids: tuple[str, ...]
    cells: tuple[SpecialtyCellBinding, ...]
    content_hashing_contract_sha256: str = CANONICAL_CONTENT_HASHING_CONTRACT_SHA256
    allocation_basis: str = ALLOCATION_BASIS
    schema_version: str = SPECIALTY_CELL_INVENTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SPECIALTY_CELL_INVENTORY_SCHEMA_VERSION:
            raise ValueError("unsupported specialty cell inventory schema")
        if self.allocation_basis != ALLOCATION_BASIS:
            raise ValueError("unsupported specialty cell allocation basis")
        if (
            self.content_hashing_contract_sha256
            != CANONICAL_CONTENT_HASHING_CONTRACT_SHA256
        ):
            raise ValueError("unsupported specialty content hashing contract")
        object.__setattr__(
            self,
            "allocator_archetype_id",
            BenchmarkArchetype(self.allocator_archetype_id),
        )
        object.__setattr__(
            self,
            "specialty",
            normalize_specialty(self.specialty),
        )
        object.__setattr__(self, "track", BenchmarkTrack(self.track))
        for name in (
            "spec_sha256",
            "plan_sha256",
            "blueprint_sha256",
            "blueprint_authoring_revision",
            "blueprint_workflow_locked_revision",
            "export_manifest_sha256",
            "export_bundle_sha256",
            "content_hashing_contract_sha256",
        ):
            _hash(getattr(self, name), name)
        for name in (
            "blueprint_id",
            "blueprint_version",
            "blueprint_schema_version",
        ):
            _text(getattr(self, name), name)

        exported_ids = tuple(self.exported_case_family_ids)
        if not exported_ids:
            raise ValueError("exported_case_family_ids must not be empty")
        for family_id in exported_ids:
            _text(family_id, "exported case family id")
        if exported_ids != tuple(sorted(exported_ids)):
            raise ValueError(
                "exported_case_family_ids must use canonical family-id order"
            )
        if len(exported_ids) != len(set(exported_ids)):
            raise ValueError("exported_case_family_ids must be unique")
        object.__setattr__(self, "exported_case_family_ids", exported_ids)

        cells = tuple(self.cells)
        if not cells or any(
            not isinstance(item, SpecialtyCellBinding) for item in cells
        ):
            raise ValueError(
                "inventory cells must contain SpecialtyCellBinding records"
            )
        cell_ids = tuple(item.cell_id for item in cells)
        if cell_ids != tuple(sorted(cell_ids)):
            raise ValueError("inventory cells must use canonical cell-id order")
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("inventory cell IDs must be unique")
        if any(
            item.specialty is not self.specialty or item.track is not self.track
            for item in cells
        ):
            raise ValueError("inventory cells must match its exact specialty and track")
        family_ids = tuple(
            family.family_id for cell in cells for family in cell.families
        )
        if len(family_ids) != len(set(family_ids)):
            raise ValueError(
                "a case family cannot be assigned to more than one plan cell"
            )
        if tuple(sorted(family_ids)) != exported_ids:
            raise ValueError(
                "inventory families must exactly equal exported_case_family_ids"
            )
        authored_item_ids = tuple(
            item_id
            for cell in cells
            for family in cell.families
            for item_id in family.authored_item_ids
        )
        if len(authored_item_ids) != len(set(authored_item_ids)):
            raise ValueError("authored item IDs must be unique across the inventory")
        authored_item_hashes = tuple(
            item.canonical_content_sha256
            for cell in cells
            for family in cell.families
            for item in family.authored_items
        )
        if len(authored_item_hashes) != len(set(authored_item_hashes)):
            raise ValueError(
                "authored item canonical content hashes must be unique "
                "across the inventory"
            )
        if any(
            cell.authored_variants_per_family != self.authored_variants_per_family
            for cell in cells
        ):
            raise ValueError("cell topology does not match the allocator archetype")
        object.__setattr__(self, "cells", cells)

    @property
    def authored_variants_per_family(self) -> int:
        return {
            BenchmarkArchetype.NOHARM: 11,
            BenchmarkArchetype.PAIRED_SPECIALTY_EQUITY: 2,
        }[BenchmarkArchetype(self.allocator_archetype_id)]

    @property
    def family_count(self) -> int:
        return len(self.exported_case_family_ids)

    @property
    def authored_variant_count(self) -> int:
        return self.family_count * self.authored_variants_per_family

    @property
    def family_to_cell(self) -> dict[str, str]:
        return {
            family.family_id: cell.cell_id
            for cell in self.cells
            for family in cell.families
        }

    @property
    def family_to_condition_family(self) -> dict[str, ConditionFamily]:
        return {
            family.family_id: family.condition_family
            for cell in self.cells
            for family in cell.families
        }

    @property
    def family_to_acuity(self) -> dict[str, AcuityLevel]:
        return {
            family.family_id: family.acuity
            for cell in self.cells
            for family in cell.families
        }

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "allocation_basis": self.allocation_basis,
            "allocator_archetype_id": BenchmarkArchetype(
                self.allocator_archetype_id
            ).value,
            "specialty": Specialty(self.specialty).value,
            "track": BenchmarkTrack(self.track).value,
            "spec_sha256": self.spec_sha256,
            "plan_sha256": self.plan_sha256,
            "content_hashing_contract_sha256": (self.content_hashing_contract_sha256),
            "blueprint": {
                "id": self.blueprint_id,
                "version": self.blueprint_version,
                "schema_version": self.blueprint_schema_version,
                "digest": self.blueprint_sha256,
                "authoring_revision": self.blueprint_authoring_revision,
                "workflow_locked_revision": (self.blueprint_workflow_locked_revision),
            },
            "export": {
                "manifest_sha256": self.export_manifest_sha256,
                "bundle_sha256": self.export_bundle_sha256,
                "case_family_ids": list(self.exported_case_family_ids),
            },
            "topology": {
                "family_count": self.family_count,
                "authored_variants_per_family": (self.authored_variants_per_family),
                "authored_variant_count": self.authored_variant_count,
            },
            "cells": [item.to_dict() for item in self.cells],
        }

    @property
    def inventory_sha256(self) -> str:
        return _digest(self._payload())

    @property
    def digest(self) -> str:
        return self.inventory_sha256

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["inventory_sha256"] = self.inventory_sha256
        return payload

    @classmethod
    def from_reviewed_blueprint(
        cls,
        plan: SpecialtyBenchmarkPlan,
        blueprint: BenchmarkBlueprint,
        *,
        specialty: Specialty | str,
        track: BenchmarkTrack | str,
        family_to_cell: Mapping[str, str] | Sequence[tuple[str, str]],
        family_to_condition_family: (
            Mapping[str, ConditionFamily | str]
            | Sequence[tuple[str, ConditionFamily | str]]
        ),
        family_to_acuity: (
            Mapping[str, AcuityLevel | str] | Sequence[tuple[str, AcuityLevel | str]]
        ),
        export_manifest_sha256: str,
        export_bundle_sha256: str,
        exported_case_family_ids: Sequence[str],
    ) -> "SpecialtyCellInventory":
        """Build an exact inventory from reviewed content and explicit mapping."""

        if not isinstance(plan, SpecialtyBenchmarkPlan):
            raise ValueError("plan must be a SpecialtyBenchmarkPlan")
        if not isinstance(blueprint, BenchmarkBlueprint):
            raise ValueError("blueprint must be a BenchmarkBlueprint")
        _hash(export_manifest_sha256, "export_manifest_sha256")
        _hash(export_bundle_sha256, "export_bundle_sha256")
        specialty_value = normalize_specialty(specialty)
        track_value = BenchmarkTrack(track)
        _validate_reviewed_blueprint(blueprint)
        try:
            blueprint_specialty = normalize_specialty(blueprint.specialty)
        except ValueError as exc:
            raise ValueError(
                "blueprint specialty cannot prove the requested specialty"
            ) from exc
        if blueprint_specialty is not specialty_value:
            raise ValueError(
                "blueprint specialty does not match the requested plan slice"
            )

        families_by_id = {family.id: family for family in blueprint.case_families}
        for family in families_by_id.values():
            try:
                family_specialty = normalize_specialty(family.base_case.specialty)
            except ValueError as exc:
                raise ValueError(
                    f"case family {family.id!r} specialty cannot prove its "
                    "plan-cell allocation"
                ) from exc
            if family_specialty is not specialty_value:
                raise ValueError(
                    f"case family {family.id!r} specialty does not match "
                    "the requested plan slice"
                )

        mapping = _explicit_text_mapping(family_to_cell, "family-to-cell")
        condition_mapping = _explicit_enum_mapping(
            family_to_condition_family,
            "family-to-condition-family",
            normalize_condition_family,
        )
        acuity_mapping = _explicit_enum_mapping(
            family_to_acuity,
            "family-to-acuity",
            AcuityLevel,
        )
        blueprint_ids = set(families_by_id)
        for label, supplied_mapping in (
            ("family-to-cell", mapping),
            ("family-to-condition-family", condition_mapping),
            ("family-to-acuity", acuity_mapping),
        ):
            mapping_ids = set(supplied_mapping)
            missing = sorted(blueprint_ids - mapping_ids)
            extra = sorted(mapping_ids - blueprint_ids)
            if missing or extra:
                raise ValueError(
                    f"{label} mapping must exactly cover the blueprint "
                    f"families; missing={missing}, extra={extra}"
                )
        if isinstance(exported_case_family_ids, (str, bytes)):
            raise ValueError("exported_case_family_ids must be a sequence of IDs")
        exported_ids = tuple(exported_case_family_ids)
        for family_id in exported_ids:
            _text(family_id, "exported case-family ID")
        if len(exported_ids) != len(set(exported_ids)):
            raise ValueError("exported case-family IDs must not contain duplicates")
        if tuple(sorted(exported_ids)) != tuple(sorted(blueprint_ids)):
            raise ValueError(
                "exported case-family set must exactly match the reviewed "
                "blueprint family set"
            )

        selected_cells = tuple(
            cell
            for cell in plan.cells
            if cell.specialty is specialty_value and cell.track is track_value
        )
        if not selected_cells:
            raise ValueError(
                "specialty plan has no cells for the requested specialty and track"
            )
        selected_by_id = {cell.cell_id: cell for cell in selected_cells}
        unknown_cells = sorted(set(mapping.values()) - set(selected_by_id))
        if unknown_cells:
            raise ValueError(
                "family-to-cell mapping contains cells outside the exact plan "
                f"slice: {unknown_cells}"
            )
        for cell in selected_cells:
            assigned_family_ids = tuple(
                family_id
                for family_id, mapped_cell_id in mapping.items()
                if mapped_cell_id == cell.cell_id
            )
            if len(assigned_family_ids) != cell.family_count:
                raise ValueError(
                    f"plan cell {cell.cell_id!r} requires exactly "
                    f"{cell.family_count} families; found "
                    f"{len(assigned_family_ids)}"
                )
            expected_conditions = {
                allocation.condition_family: allocation.family_count
                for allocation in cell.condition_allocations
            }
            actual_conditions = Counter(
                condition_mapping[family_id] for family_id in assigned_family_ids
            )
            if dict(actual_conditions) != expected_conditions:
                raise ValueError(
                    f"plan cell {cell.cell_id!r} family condition assignments "
                    "must equal its exact condition allocation"
                )
            expected_acuities = {
                allocation.acuity: allocation.family_count
                for allocation in cell.acuity_allocations
            }
            acuity_counts = Counter(
                acuity_mapping[family_id] for family_id in assigned_family_ids
            )
            actual_acuities = {
                level: acuity_counts.get(level, 0) for level in CANONICAL_ACUITY_LEVELS
            }
            if actual_acuities != expected_acuities:
                raise ValueError(
                    f"plan cell {cell.cell_id!r} family acuity assignments "
                    "must equal its exact acuity allocation"
                )

        _validate_blueprint_topology(plan, blueprint)
        bindings = tuple(
            _cell_binding(
                cell,
                tuple(
                    families_by_id[family_id]
                    for family_id in sorted(families_by_id)
                    if mapping[family_id] == cell.cell_id
                ),
                condition_mapping,
                acuity_mapping,
            )
            for cell in sorted(selected_cells, key=lambda value: value.cell_id)
        )
        workflow_lock = blueprint.workflow_locked_revision
        if workflow_lock is None:
            raise ValueError("reviewed blueprint is missing its workflow lock")
        return cls(
            allocator_archetype_id=plan.spec.archetype,
            specialty=specialty_value,
            track=track_value,
            spec_sha256=plan.spec.spec_sha256,
            plan_sha256=plan.plan_sha256,
            blueprint_id=blueprint.id,
            blueprint_version=blueprint.version,
            blueprint_schema_version=blueprint.schema_version,
            blueprint_sha256=blueprint.digest,
            blueprint_authoring_revision=blueprint.authoring_revision,
            blueprint_workflow_locked_revision=workflow_lock,
            export_manifest_sha256=export_manifest_sha256,
            export_bundle_sha256=export_bundle_sha256,
            exported_case_family_ids=tuple(sorted(exported_ids)),
            cells=bindings,
        )

    def validate_against(
        self,
        plan: SpecialtyBenchmarkPlan,
        blueprint: BenchmarkBlueprint,
    ) -> None:
        """Fail unless this inventory is the exact current plan/content bridge."""

        expected = type(self).from_reviewed_blueprint(
            plan,
            blueprint,
            specialty=self.specialty,
            track=self.track,
            family_to_cell=self.family_to_cell,
            family_to_condition_family=self.family_to_condition_family,
            family_to_acuity=self.family_to_acuity,
            export_manifest_sha256=self.export_manifest_sha256,
            export_bundle_sha256=self.export_bundle_sha256,
            exported_case_family_ids=self.exported_case_family_ids,
        )
        if expected.to_dict() != self.to_dict():
            raise ValueError(
                "specialty cell inventory is stale relative to the plan or blueprint"
            )

    def validate_plan_slice(self, plan: SpecialtyBenchmarkPlan) -> None:
        """Fail unless the inventory exactly materializes its declared plan slice."""

        if not isinstance(plan, SpecialtyBenchmarkPlan):
            raise ValueError("plan must be a SpecialtyBenchmarkPlan")
        if self.spec_sha256 != plan.spec.spec_sha256:
            raise ValueError("specialty cell inventory has a stale spec digest")
        if self.plan_sha256 != plan.plan_sha256:
            raise ValueError("specialty cell inventory has a stale plan digest")
        if self.allocator_archetype_id is not plan.spec.archetype:
            raise ValueError(
                "specialty cell inventory allocator archetype does not match the plan"
            )

        expected_cells = tuple(
            cell
            for cell in plan.cells
            if cell.specialty is self.specialty and cell.track is self.track
        )
        if not expected_cells:
            raise ValueError(
                "specialty plan has no cells for the inventory specialty and track"
            )
        expected_by_id = {cell.cell_id: cell for cell in expected_cells}
        actual_by_id = {cell.cell_id: cell for cell in self.cells}
        if set(expected_by_id) != set(actual_by_id):
            raise ValueError(
                "specialty cell inventory does not cover the exact plan slice"
            )
        for cell_id, expected in expected_by_id.items():
            actual = actual_by_id[cell_id]
            if actual.cell_sha256 != _digest(expected.to_dict()):
                raise ValueError(
                    f"specialty cell inventory has a stale cell digest for {cell_id!r}"
                )
            if actual.expected_family_count != expected.family_count:
                raise ValueError(
                    f"specialty cell inventory has a stale family count for {cell_id!r}"
                )
            if actual.authored_variants_per_family != expected.variants_per_family:
                raise ValueError(
                    f"specialty cell inventory has stale topology for {cell_id!r}"
                )
            if actual.condition_allocations != expected.condition_allocations:
                raise ValueError(
                    "specialty cell inventory has stale condition allocations "
                    f"for {cell_id!r}"
                )
            if actual.acuity_allocations != expected.acuity_allocations:
                raise ValueError(
                    "specialty cell inventory has stale acuity allocations "
                    f"for {cell_id!r}"
                )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialtyCellInventory":
        _fields(
            data,
            {
                "schema_version",
                "allocation_basis",
                "allocator_archetype_id",
                "specialty",
                "track",
                "spec_sha256",
                "plan_sha256",
                "content_hashing_contract_sha256",
                "blueprint",
                "export",
                "topology",
                "cells",
                "inventory_sha256",
            },
            "specialty cell inventory",
        )
        blueprint = _mapping(data["blueprint"], "blueprint")
        _fields(
            blueprint,
            {
                "id",
                "version",
                "schema_version",
                "digest",
                "authoring_revision",
                "workflow_locked_revision",
            },
            "specialty cell inventory blueprint",
        )
        export = _mapping(data["export"], "export")
        _fields(
            export,
            {"manifest_sha256", "bundle_sha256", "case_family_ids"},
            "specialty cell inventory export",
        )
        topology = _mapping(data["topology"], "topology")
        _fields(
            topology,
            {
                "family_count",
                "authored_variants_per_family",
                "authored_variant_count",
            },
            "specialty cell inventory topology",
        )
        result = cls(
            schema_version=_string(data["schema_version"], "schema_version"),
            allocation_basis=_string(data["allocation_basis"], "allocation_basis"),
            allocator_archetype_id=_string(
                data["allocator_archetype_id"], "allocator_archetype_id"
            ),
            specialty=_string(data["specialty"], "specialty"),
            track=_string(data["track"], "track"),
            spec_sha256=_string(data["spec_sha256"], "spec_sha256"),
            plan_sha256=_string(data["plan_sha256"], "plan_sha256"),
            content_hashing_contract_sha256=_string(
                data["content_hashing_contract_sha256"],
                "content hashing contract SHA-256",
            ),
            blueprint_id=_string(blueprint["id"], "blueprint id"),
            blueprint_version=_string(blueprint["version"], "blueprint version"),
            blueprint_schema_version=_string(
                blueprint["schema_version"], "blueprint schema_version"
            ),
            blueprint_sha256=_string(blueprint["digest"], "blueprint digest"),
            blueprint_authoring_revision=_string(
                blueprint["authoring_revision"], "blueprint authoring revision"
            ),
            blueprint_workflow_locked_revision=_string(
                blueprint["workflow_locked_revision"],
                "blueprint workflow locked revision",
            ),
            export_manifest_sha256=_string(
                export["manifest_sha256"], "export manifest SHA-256"
            ),
            export_bundle_sha256=_string(
                export["bundle_sha256"], "export bundle SHA-256"
            ),
            exported_case_family_ids=_string_tuple(
                export["case_family_ids"], "exported case family IDs"
            ),
            cells=tuple(
                SpecialtyCellBinding.from_dict(item)
                for item in _mapping_tuple(data["cells"], "cells")
            ),
        )
        if topology != result._payload()["topology"]:
            raise ValueError("specialty cell inventory topology is not derived")
        if data["inventory_sha256"] != result.inventory_sha256:
            raise ValueError("specialty cell inventory hash mismatch")
        if dict(data) != result.to_dict():
            raise ValueError("specialty cell inventory is not canonical")
        return result

    @classmethod
    def from_json(cls, payload: str) -> "SpecialtyCellInventory":
        return cls.from_dict(strict_json_object(payload, "specialty cell inventory", finite_floats=True))


def _validate_reviewed_blueprint(blueprint: BenchmarkBlueprint) -> None:
    if blueprint.review_stage != "workflow_complete":
        raise ValueError("blueprint must be workflow_complete")
    if blueprint.workflow_locked_revision != blueprint.authoring_revision:
        raise ValueError("blueprint workflow lock is stale")
    if any(
        family.review.stage != "workflow_complete" for family in blueprint.case_families
    ):
        raise ValueError("every blueprint case family must be workflow_complete")


def _validate_blueprint_topology(
    plan: SpecialtyBenchmarkPlan,
    blueprint: BenchmarkBlueprint,
) -> None:
    variants_per_family = plan.spec.variants_per_family
    expected_derivatives = variants_per_family - 1
    if blueprint.expected_variants_per_base != expected_derivatives:
        raise ValueError(
            "blueprint expected_variants_per_base cannot prove the plan topology"
        )
    if plan.spec.archetype is BenchmarkArchetype.NOHARM:
        if not blueprint.strict_noharm_topology:
            raise ValueError(
                "NOHARM inventory requires a strict-NOHARM reviewed blueprint"
            )
    elif blueprint.strict_noharm_topology:
        raise ValueError("paired-specialty inventory cannot use strict NOHARM topology")
    for family in blueprint.case_families:
        if len(family.variants) != expected_derivatives:
            raise ValueError(
                f"case family {family.id!r} does not match the plan topology"
            )
        authored_ids = (family.id, *(variant.id for variant in family.variants))
        if len(authored_ids) != len(set(authored_ids)):
            raise ValueError(
                f"case family {family.id!r} has duplicate authored item IDs"
            )
        if plan.spec.archetype is BenchmarkArchetype.NOHARM:
            expected_ids = (
                family.id,
                *(f"{family.id}-{index}" for index in range(10)),
            )
            if tuple(authored_ids) != expected_ids:
                raise ValueError(
                    f"case family {family.id!r} does not have canonical "
                    "NOHARM variant IDs"
                )


def _cell_binding(
    cell: SubBenchmarkCell,
    families: tuple[CaseFamily, ...],
    condition_mapping: Mapping[str, ConditionFamily],
    acuity_mapping: Mapping[str, AcuityLevel],
) -> SpecialtyCellBinding:
    return SpecialtyCellBinding(
        cell_id=cell.cell_id,
        cell_sha256=_digest(cell.to_dict()),
        specialty=cell.specialty,
        track=cell.track,
        expected_family_count=cell.family_count,
        authored_variants_per_family=cell.variants_per_family,
        condition_allocations=cell.condition_allocations,
        acuity_allocations=cell.acuity_allocations,
        families=tuple(
            _family_binding(
                family,
                condition_family=condition_mapping[family.id],
                acuity=acuity_mapping[family.id],
            )
            for family in families
        ),
    )


def _family_binding(
    family: CaseFamily,
    *,
    condition_family: ConditionFamily,
    acuity: AcuityLevel,
) -> AuthoredFamilyBinding:
    authored_items = (
        AuthoredItemBinding(
            item_id=family.id,
            canonical_content_sha256=canonical_item_content_sha256(
                family.base_case.presentation.value
            ),
        ),
        *(
            AuthoredItemBinding(
                item_id=variant.id,
                canonical_content_sha256=canonical_item_content_sha256(
                    variant.presentation.value
                ),
            )
            for variant in family.variants
        ),
    )
    return AuthoredFamilyBinding(
        family_id=family.id,
        case_family_sha256=_digest(family.to_dict()),
        canonical_content_sha256=canonical_family_content_sha256(
            tuple(item.canonical_content_sha256 for item in authored_items)
        ),
        workflow_revision=family.workflow_revision,
        base_specialty=family.base_case.specialty,
        condition_family=condition_family,
        acuity=acuity,
        authored_items=authored_items,
    )


def validate_cross_track_inventory_isolation(
    inventories: Sequence[SpecialtyCellInventory],
) -> None:
    """Reject representative/stress source overlap within a program specialty.

    A program is identified by the exact specialty-program spec digest. The
    function compares only inventories for the same spec and specialty, while
    accepting collections that span programs or specialties.
    """

    if isinstance(inventories, (str, bytes)):
        raise ValueError("inventories must be a sequence of inventory records")
    try:
        values = tuple(inventories)
    except TypeError as exc:
        raise ValueError("inventories must be a sequence of inventory records") from exc
    if any(not isinstance(item, SpecialtyCellInventory) for item in values):
        raise ValueError("inventories must contain SpecialtyCellInventory records")
    inventory_keys = tuple(
        (item.spec_sha256, item.specialty, item.track) for item in values
    )
    if len(inventory_keys) != len(set(inventory_keys)):
        raise ValueError(
            "inventory collection contains a duplicate program/specialty/track"
        )

    grouped: dict[
        tuple[str, Specialty],
        dict[BenchmarkTrack, SpecialtyCellInventory],
    ] = {}
    for inventory in values:
        group = grouped.setdefault(
            (inventory.spec_sha256, inventory.specialty),
            {},
        )
        group[inventory.track] = inventory

    for (spec_sha256, specialty), tracks in grouped.items():
        if set(tracks) != set(BenchmarkTrack):
            continue
        representative = tracks[BenchmarkTrack.REPRESENTATIVE]
        stress = tracks[BenchmarkTrack.STRESS]
        if representative.plan_sha256 != stress.plan_sha256:
            raise ValueError(
                "cross-track inventories for one program/specialty have "
                "different plan digests"
            )
        if representative.allocator_archetype_id is not stress.allocator_archetype_id:
            raise ValueError(
                "cross-track inventories for one program/specialty have "
                "different allocator archetypes"
            )

        representative_families = _inventory_families(representative)
        stress_families = _inventory_families(stress)
        overlapping_family_ids = sorted(
            {item.family_id for item in representative_families}
            & {item.family_id for item in stress_families}
        )
        if overlapping_family_ids:
            raise ValueError(
                "representative and stress inventories overlap on family IDs "
                f"for {spec_sha256}/{specialty.value}: "
                f"{overlapping_family_ids}"
            )

        representative_item_ids = {
            item_id
            for family in representative_families
            for item_id in family.authored_item_ids
        }
        stress_item_ids = {
            item_id
            for family in stress_families
            for item_id in family.authored_item_ids
        }
        overlapping_item_ids = sorted(representative_item_ids & stress_item_ids)
        if overlapping_item_ids:
            raise ValueError(
                "representative and stress inventories overlap on authored "
                f"item IDs for {spec_sha256}/{specialty.value}: "
                f"{overlapping_item_ids}"
            )

        overlapping_content_hashes = sorted(
            {item.canonical_content_sha256 for item in representative_families}
            & {item.canonical_content_sha256 for item in stress_families}
        )
        if overlapping_content_hashes:
            raise ValueError(
                "representative and stress inventories overlap on canonical "
                f"content hashes for {spec_sha256}/{specialty.value}: "
                f"{overlapping_content_hashes}"
            )
        representative_item_hashes = {
            item.canonical_content_sha256
            for family in representative_families
            for item in family.authored_items
        }
        stress_item_hashes = {
            item.canonical_content_sha256
            for family in stress_families
            for item in family.authored_items
        }
        overlapping_item_hashes = sorted(
            representative_item_hashes & stress_item_hashes
        )
        if overlapping_item_hashes:
            raise ValueError(
                "representative and stress inventories overlap on canonical "
                f"item content hashes for {spec_sha256}/{specialty.value}: "
                f"{overlapping_item_hashes}"
            )


def _inventory_families(
    inventory: SpecialtyCellInventory,
) -> tuple[AuthoredFamilyBinding, ...]:
    return tuple(family for cell in inventory.cells for family in cell.families)


def _explicit_text_mapping(
    supplied: Mapping[str, str] | Sequence[tuple[str, str]],
    label: str,
) -> dict[str, str]:
    if isinstance(supplied, Mapping):
        pairs = tuple(supplied.items())
    else:
        if isinstance(supplied, (str, bytes)):
            raise ValueError(f"{label} must be a mapping or sequence of pairs")
        try:
            pairs = tuple(supplied)
        except TypeError as exc:
            raise ValueError(f"{label} must be a mapping or sequence of pairs") from exc
    result: dict[str, str] = {}
    for pair in pairs:
        if (
            not isinstance(pair, Sequence)
            or isinstance(pair, (str, bytes))
            or len(pair) != 2
        ):
            raise ValueError(f"{label} entries must be (family_id, value) pairs")
        family_id, value = pair
        _text(family_id, "mapped family_id")
        _text(value, f"{label} value")
        if family_id in result:
            raise ValueError(f"duplicate {label} mapping for {family_id!r}")
        result[family_id] = value
    if not result:
        raise ValueError(f"{label} must not be empty")
    return result


def _explicit_enum_mapping(
    supplied: Mapping[str, Any] | Sequence[tuple[str, Any]],
    label: str,
    constructor: Any,
) -> dict[str, Any]:
    if isinstance(supplied, Mapping):
        pairs = tuple(supplied.items())
    else:
        if isinstance(supplied, (str, bytes)):
            raise ValueError(f"{label} must be a mapping or sequence of pairs")
        try:
            pairs = tuple(supplied)
        except TypeError as exc:
            raise ValueError(f"{label} must be a mapping or sequence of pairs") from exc
    result: dict[str, Any] = {}
    for pair in pairs:
        if (
            not isinstance(pair, Sequence)
            or isinstance(pair, (str, bytes))
            or len(pair) != 2
        ):
            raise ValueError(f"{label} entries must be (family_id, value) pairs")
        family_id, value = pair
        _text(family_id, "mapped family_id")
        if family_id in result:
            raise ValueError(f"duplicate {label} mapping for {family_id!r}")
        try:
            result[family_id] = constructor(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} has an invalid value for {family_id!r}") from exc
    if not result:
        raise ValueError(f"{label} must not be empty")
    return result


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _mapping_tuple(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{label} entries must be objects")
    return tuple(value)


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(_string(item, f"{label} item") for item in value)


__all__ = [
    "ALLOCATION_BASIS",
    "SPECIALTY_CELL_INVENTORY_SCHEMA_VERSION",
    "AuthoredFamilyBinding",
    "AuthoredItemBinding",
    "SpecialtyCellBinding",
    "SpecialtyCellInventory",
    "validate_cross_track_inventory_isolation",
]

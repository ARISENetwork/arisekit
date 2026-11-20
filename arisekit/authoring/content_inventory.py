"""Strict content inventories for reference-arm parity selections.

The inventory binds identifiers to externally computed canonical content
hashes. It does not inspect clinical content or decide which families belong
in a comparison.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from arisekit.common.hashing import canonical_sha256 as _digest
from arisekit.common.jsonio import strict_json_object
from arisekit.common.records import CanonicalPropertyRecord
from arisekit.common.validate import exact_fields as _fields, sha256_hex, text


REFERENCE_SELECTION_INVENTORY_SCHEMA_VERSION = (
    "arisekit.reference-selection-inventory.v2"
)
CANONICAL_CONTENT_HASHING_CONTRACT_SCHEMA_VERSION = (
    "arisekit.canonical-content-hashing-contract.v1"
)
CANONICAL_ITEM_CONTENT_SCHEMA_VERSION = "arisekit.canonical-item-content.v1"
CANONICAL_FAMILY_CONTENT_SCHEMA_VERSION = "arisekit.canonical-family-content.v1"


def _content_hashing_contract_payload() -> dict[str, Any]:
    return {
        "schema_version": CANONICAL_CONTENT_HASHING_CONTRACT_SCHEMA_VERSION,
        "digest_algorithm": "sha256",
        "serialization": {
            "format": "json",
            "sort_keys": True,
            "separators": [",", ":"],
            "ensure_ascii": False,
            "allow_nan": False,
            "text_normalization": "none-exact-authored-unicode",
        },
        "item_projection": {
            "schema_version": CANONICAL_ITEM_CONTENT_SCHEMA_VERSION,
            "fields": ["schema_version", "presentation"],
            "identity_fields": [],
        },
        "family_projection": {
            "schema_version": CANONICAL_FAMILY_CONTENT_SCHEMA_VERSION,
            "fields": ["schema_version", "sorted_item_content_sha256s"],
            "identity_fields": [],
        },
    }


CANONICAL_CONTENT_HASHING_CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(
        _content_hashing_contract_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
).hexdigest()


def canonical_item_content_sha256(presentation: str) -> str:
    """Hash exact authored presentation text without any item identifier."""

    _text("canonical item presentation", presentation)
    return _digest(
        {
            "schema_version": CANONICAL_ITEM_CONTENT_SCHEMA_VERSION,
            "presentation": presentation,
        }
    )


def canonical_family_content_sha256(
    item_content_sha256s: tuple[str, ...] | list[str],
) -> str:
    """Hash an ID- and order-independent set of canonical authored items."""

    if isinstance(item_content_sha256s, (str, bytes)):
        raise ValueError("family item content hashes must be a sequence")
    try:
        values = tuple(item_content_sha256s)
    except TypeError as exc:
        raise ValueError("family item content hashes must be a sequence") from exc
    if not values:
        raise ValueError("family item content hashes must not be empty")
    for value in values:
        _hash("family item content hash", value)
    if len(values) != len(set(values)):
        raise ValueError("family item content hashes must be unique")
    return _digest(
        {
            "schema_version": CANONICAL_FAMILY_CONTENT_SCHEMA_VERSION,
            "sorted_item_content_sha256s": sorted(values),
        }
    )


@dataclass(frozen=True, slots=True)
class ContentItemBinding:
    item_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text("content item ID", self.item_id)
        _hash("content item hash", self.content_sha256)

    def to_dict(self) -> dict[str, str]:
        return {
            "item_id": self.item_id,
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContentItemBinding":
        _fields(data, {"item_id", "content_sha256"}, "content item binding")
        return cls(
            item_id=data["item_id"],
            content_sha256=data["content_sha256"],
        )


@dataclass(frozen=True, slots=True)
class ContentFamilyBinding:
    family_id: str
    family_content_sha256: str
    baseline_item_id: str
    items: tuple[ContentItemBinding, ...]

    def __post_init__(self) -> None:
        _text("content family ID", self.family_id)
        _hash("content family hash", self.family_content_sha256)
        _text("baseline item ID", self.baseline_item_id)
        items = tuple(self.items)
        if not items or not all(isinstance(item, ContentItemBinding) for item in items):
            raise ValueError(
                "content family items must contain ContentItemBinding records"
            )
        item_ids = tuple(item.item_id for item in items)
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("content family item IDs must be unique")
        if self.baseline_item_id not in item_ids:
            raise ValueError("content family baseline must be one of its items")
        expected_family_hash = canonical_family_content_sha256(
            [item.content_sha256 for item in items]
        )
        if self.family_content_sha256 != expected_family_hash:
            raise ValueError(
                "content family hash must be derived from its canonical item hashes"
            )
        object.__setattr__(
            self,
            "items",
            tuple(sorted(items, key=lambda item: item.item_id)),
        )

    @property
    def item_ids(self) -> tuple[str, ...]:
        return tuple(item.item_id for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "family_content_sha256": self.family_content_sha256,
            "baseline_item_id": self.baseline_item_id,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContentFamilyBinding":
        _fields(
            data,
            {
                "family_id",
                "family_content_sha256",
                "baseline_item_id",
                "items",
            },
            "content family binding",
        )
        if not isinstance(data["items"], list):
            raise ValueError("content family items must be a list")
        return cls(
            family_id=data["family_id"],
            family_content_sha256=data["family_content_sha256"],
            baseline_item_id=data["baseline_item_id"],
            items=tuple(ContentItemBinding.from_dict(item) for item in data["items"]),
        )


@dataclass(frozen=True, slots=True)
class ReferenceSelectionInventory(CanonicalPropertyRecord):
    """Exact selected reference families and content hashes for one bundle."""

    bundle_sha256: str
    source_manifest_sha256: str
    source_revision: str
    selection_protocol_sha256: str
    selection_commit_sha256: str
    families: tuple[ContentFamilyBinding, ...]
    content_hashing_contract_sha256: str = CANONICAL_CONTENT_HASHING_CONTRACT_SHA256
    schema_version: str = REFERENCE_SELECTION_INVENTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REFERENCE_SELECTION_INVENTORY_SCHEMA_VERSION:
            raise ValueError("unsupported reference selection inventory schema")
        if (
            self.content_hashing_contract_sha256
            != CANONICAL_CONTENT_HASHING_CONTRACT_SHA256
        ):
            raise ValueError("unsupported reference content hashing contract")
        for name in (
            "bundle_sha256",
            "source_manifest_sha256",
            "selection_protocol_sha256",
            "selection_commit_sha256",
            "content_hashing_contract_sha256",
        ):
            _hash(name, getattr(self, name))
        _text("reference source revision", self.source_revision)
        families = tuple(self.families)
        if not families or not all(
            isinstance(family, ContentFamilyBinding) for family in families
        ):
            raise ValueError(
                "reference inventory families must contain ContentFamilyBinding records"
            )
        family_ids = tuple(family.family_id for family in families)
        if len(set(family_ids)) != len(family_ids):
            raise ValueError("reference inventory family IDs must be unique")
        item_ids = tuple(item.item_id for family in families for item in family.items)
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("reference inventory item IDs must be globally unique")
        family_hashes = tuple(family.family_content_sha256 for family in families)
        if len(set(family_hashes)) != len(family_hashes):
            raise ValueError("reference inventory family content hashes must be unique")
        item_hashes = tuple(
            item.content_sha256 for family in families for item in family.items
        )
        if len(set(item_hashes)) != len(item_hashes):
            raise ValueError("reference inventory item content hashes must be unique")
        object.__setattr__(
            self,
            "families",
            tuple(sorted(families, key=lambda family: family.family_id)),
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_sha256": self.bundle_sha256,
            "source_manifest_sha256": self.source_manifest_sha256,
            "source_revision": self.source_revision,
            "selection_protocol_sha256": self.selection_protocol_sha256,
            "selection_commit_sha256": self.selection_commit_sha256,
            "content_hashing_contract_sha256": (self.content_hashing_contract_sha256),
            "families": [family.to_dict() for family in self.families],
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
    def from_dict(cls, data: Mapping[str, Any]) -> "ReferenceSelectionInventory":
        _fields(
            data,
            {
                "schema_version",
                "bundle_sha256",
                "source_manifest_sha256",
                "source_revision",
                "selection_protocol_sha256",
                "selection_commit_sha256",
                "content_hashing_contract_sha256",
                "families",
                "inventory_sha256",
            },
            "reference selection inventory",
        )
        if not isinstance(data["families"], list):
            raise ValueError("reference inventory families must be a list")
        result = cls(
            schema_version=data["schema_version"],
            bundle_sha256=data["bundle_sha256"],
            source_manifest_sha256=data["source_manifest_sha256"],
            source_revision=data["source_revision"],
            selection_protocol_sha256=data["selection_protocol_sha256"],
            selection_commit_sha256=data["selection_commit_sha256"],
            content_hashing_contract_sha256=data["content_hashing_contract_sha256"],
            families=tuple(
                ContentFamilyBinding.from_dict(item) for item in data["families"]
            ),
        )
        if data["inventory_sha256"] != result.inventory_sha256:
            raise ValueError("reference selection inventory hash mismatch")
        if result.to_dict() != dict(data):
            raise ValueError("reference selection inventory is not canonical")
        return result

    @classmethod
    def from_json(cls, payload: str) -> "ReferenceSelectionInventory":
        return cls.from_dict(
            strict_json_object(payload, "reference selection inventory", finite_floats=True)
        )


def _text(label: str, value: Any) -> str:
    return text(value, label)


def _hash(name: str, value: Any) -> str:
    return sha256_hex(value, name)


__all__ = [
    "CANONICAL_CONTENT_HASHING_CONTRACT_SCHEMA_VERSION",
    "CANONICAL_CONTENT_HASHING_CONTRACT_SHA256",
    "CANONICAL_FAMILY_CONTENT_SCHEMA_VERSION",
    "CANONICAL_ITEM_CONTENT_SCHEMA_VERSION",
    "REFERENCE_SELECTION_INVENTORY_SCHEMA_VERSION",
    "ContentFamilyBinding",
    "ContentItemBinding",
    "ReferenceSelectionInventory",
    "canonical_family_content_sha256",
    "canonical_item_content_sha256",
]

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from arisekit.authoring.content_inventory import (
    CANONICAL_CONTENT_HASHING_CONTRACT_SHA256,
    REFERENCE_SELECTION_INVENTORY_SCHEMA_VERSION,
    ContentFamilyBinding,
    ContentItemBinding,
    ReferenceSelectionInventory,
    canonical_family_content_sha256,
    canonical_item_content_sha256,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _item(item_id: str, *, content_label: str | None = None) -> ContentItemBinding:
    return ContentItemBinding(
        item_id=item_id,
        content_sha256=canonical_item_content_sha256(
            content_label or f"content:{item_id}"
        ),
    )


def _family(
    family_id: str,
    *,
    family_content_label: str | None = None,
    item_ids: tuple[str, ...] | None = None,
    baseline_item_id: str | None = None,
) -> ContentFamilyBinding:
    resolved_item_ids = item_ids or (
        f"{family_id}-baseline",
        f"{family_id}-variant-1",
        f"{family_id}-variant-2",
    )
    items = tuple(
        _item(
            item_id,
            content_label=(
                f"{family_content_label}:item-{index}"
                if family_content_label is not None
                else None
            ),
        )
        for index, item_id in enumerate(resolved_item_ids)
    )
    return ContentFamilyBinding(
        family_id=family_id,
        family_content_sha256=canonical_family_content_sha256(
            [item.content_sha256 for item in items]
        ),
        baseline_item_id=baseline_item_id or resolved_item_ids[0],
        items=items,
    )


def _inventory(
    *,
    families: tuple[ContentFamilyBinding, ...] | None = None,
    source_revision: str = "release-v1",
) -> ReferenceSelectionInventory:
    return ReferenceSelectionInventory(
        bundle_sha256=_hash("bundle"),
        source_manifest_sha256=_hash("source-manifest"),
        source_revision=source_revision,
        selection_protocol_sha256=_hash("selection-protocol"),
        selection_commit_sha256=_hash("selection-commit"),
        families=(
            families
            if families is not None
            else (_family("family-b"), _family("family-a"))
        ),
    )


def _rehash_inventory_payload(payload: dict[str, object]) -> None:
    digest_payload = {
        key: value for key, value in payload.items() if key != "inventory_sha256"
    }
    canonical = json.dumps(
        digest_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    payload["inventory_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_reference_inventory_round_trips_canonical_json_and_sorts_records() -> None:
    inventory = _inventory()

    assert tuple(family.family_id for family in inventory.families) == (
        "family-a",
        "family-b",
    )
    assert inventory.families[0].item_ids == (
        "family-a-baseline",
        "family-a-variant-1",
        "family-a-variant-2",
    )
    assert inventory.digest == inventory.inventory_sha256
    assert ReferenceSelectionInventory.from_dict(inventory.to_dict()) == inventory
    assert ReferenceSelectionInventory.from_json(inventory.canonical_json) == inventory
    assert (
        ReferenceSelectionInventory.from_json(inventory.canonical_json).canonical_json
        == inventory.canonical_json
    )
    assert inventory.to_dict()["schema_version"] == (
        REFERENCE_SELECTION_INVENTORY_SCHEMA_VERSION
    )
    assert (
        inventory.content_hashing_contract_sha256
        == CANONICAL_CONTENT_HASHING_CONTRACT_SHA256
    )
    assert inventory.to_dict()["content_hashing_contract_sha256"] == (
        CANONICAL_CONTENT_HASHING_CONTRACT_SHA256
    )


def test_canonical_content_hashes_are_identity_independent_and_family_derived() -> None:
    first = canonical_item_content_sha256("Exact authored presentation.")
    relabelled = canonical_item_content_sha256("Exact authored presentation.")
    changed = canonical_item_content_sha256("Changed authored presentation.")

    assert first == relabelled
    assert first != changed
    assert canonical_family_content_sha256([first, changed]) == (
        canonical_family_content_sha256([changed, first])
    )

    with pytest.raises(
        ValueError,
        match="content family hash must be derived from its canonical item hashes",
    ):
        ContentFamilyBinding(
            family_id="family-a",
            family_content_sha256=_hash("caller-asserted-family-hash"),
            baseline_item_id="baseline",
            items=(_item("baseline"), _item("variant")),
        )


def test_reference_inventory_rejects_other_content_hashing_contract() -> None:
    with pytest.raises(
        ValueError,
        match="unsupported reference content hashing contract",
    ):
        ReferenceSelectionInventory(
            bundle_sha256=_hash("bundle"),
            source_manifest_sha256=_hash("source-manifest"),
            source_revision="release-v1",
            selection_protocol_sha256=_hash("selection-protocol"),
            selection_commit_sha256=_hash("selection-commit"),
            families=(_family("family-a"),),
            content_hashing_contract_sha256=_hash("other-contract"),
        )


def test_equivalent_constructor_order_produces_identical_inventory_digest() -> None:
    family_a = _family(
        "family-a",
        item_ids=(
            "family-a-variant-2",
            "family-a-baseline",
            "family-a-variant-1",
        ),
        baseline_item_id="family-a-baseline",
    )
    family_b = _family("family-b")

    forward = _inventory(families=(family_a, family_b))
    reverse = _inventory(families=(family_b, family_a))

    assert forward.canonical_json == reverse.canonical_json
    assert forward.inventory_sha256 == reverse.inventory_sha256


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("bundle_sha256", _hash("tampered-bundle")),
        ("source_manifest_sha256", _hash("tampered-source-manifest")),
        ("source_revision", "release-v2"),
        ("selection_protocol_sha256", _hash("tampered-protocol")),
        ("selection_commit_sha256", _hash("tampered-commit")),
    ),
)
def test_unrehashed_provenance_tampering_is_rejected(
    field: str, replacement: str
) -> None:
    payload = _inventory().to_dict()
    payload[field] = replacement

    with pytest.raises(ValueError, match="reference selection inventory hash mismatch"):
        ReferenceSelectionInventory.from_dict(payload)


def test_unrehashed_family_and_item_content_tampering_is_rejected() -> None:
    family_payload = _inventory().to_dict()
    family_payload["families"][0]["family_content_sha256"] = _hash(
        "tampered-family-content"
    )
    with pytest.raises(ValueError, match="content family hash must be derived"):
        ReferenceSelectionInventory.from_dict(family_payload)

    item_payload = _inventory().to_dict()
    item_payload["families"][0]["items"][0]["content_sha256"] = _hash(
        "tampered-item-content"
    )
    with pytest.raises(ValueError, match="content family hash must be derived"):
        ReferenceSelectionInventory.from_dict(item_payload)


def test_supplied_inventory_digest_cannot_be_replaced_independently() -> None:
    payload = _inventory().to_dict()
    payload["inventory_sha256"] = _hash("forged-inventory")

    with pytest.raises(ValueError, match="reference selection inventory hash mismatch"):
        ReferenceSelectionInventory.from_dict(payload)


def test_noncanonical_family_or_item_order_is_rejected() -> None:
    family_order_payload = _inventory().to_dict()
    family_order_payload["families"].reverse()

    with pytest.raises(
        ValueError, match="reference selection inventory is not canonical"
    ):
        ReferenceSelectionInventory.from_dict(family_order_payload)

    item_order_payload = _inventory().to_dict()
    item_order_payload["families"][0]["items"].reverse()

    with pytest.raises(
        ValueError, match="reference selection inventory is not canonical"
    ):
        ReferenceSelectionInventory.from_dict(item_order_payload)


def test_family_requires_a_real_member_as_its_baseline() -> None:
    with pytest.raises(
        ValueError, match="content family baseline must be one of its items"
    ):
        ContentFamilyBinding(
            family_id="family-a",
            family_content_sha256=_hash("family-a"),
            baseline_item_id="not-a-member",
            items=(_item("family-a-variant-1"),),
        )


def test_rehashed_baseline_tampering_cannot_reference_another_family() -> None:
    payload = _inventory().to_dict()
    payload["families"][0]["baseline_item_id"] = payload["families"][1][
        "baseline_item_id"
    ]
    _rehash_inventory_payload(payload)

    with pytest.raises(
        ValueError, match="content family baseline must be one of its items"
    ):
        ReferenceSelectionInventory.from_dict(payload)


def test_family_rejects_empty_items_and_duplicate_item_ids() -> None:
    with pytest.raises(
        ValueError,
        match="content family items must contain ContentItemBinding records",
    ):
        ContentFamilyBinding(
            family_id="family-a",
            family_content_sha256=_hash("family-a"),
            baseline_item_id="family-a-baseline",
            items=(),
        )

    duplicate = _item("family-a-baseline")
    with pytest.raises(ValueError, match="content family item IDs must be unique"):
        ContentFamilyBinding(
            family_id="family-a",
            family_content_sha256=_hash("family-a"),
            baseline_item_id="family-a-baseline",
            items=(duplicate, duplicate),
        )


def test_inventory_rejects_duplicate_family_ids() -> None:
    with pytest.raises(
        ValueError, match="reference inventory family IDs must be unique"
    ):
        _inventory(
            families=(
                _family("family-a"),
                _family(
                    "family-a",
                    family_content_label="different-family-content",
                    item_ids=(
                        "different-baseline",
                        "different-variant",
                    ),
                ),
            )
        )


def test_inventory_rejects_duplicate_item_ids_across_families() -> None:
    with pytest.raises(
        ValueError, match="reference inventory item IDs must be globally unique"
    ):
        _inventory(
            families=(
                _family("family-a"),
                _family(
                    "family-b",
                    item_ids=(
                        "family-a-baseline",
                        "family-b-variant-1",
                    ),
                    baseline_item_id="family-a-baseline",
                ),
            )
        )


def test_inventory_rejects_duplicate_family_content_hashes() -> None:
    with pytest.raises(
        ValueError,
        match="reference inventory family content hashes must be unique",
    ):
        _inventory(
            families=(
                _family("family-a", family_content_label="same-content"),
                _family("family-b", family_content_label="same-content"),
            )
        )


def test_inventory_rejects_duplicate_item_content_hashes_across_families() -> None:
    duplicate_content = "shared-item-content"
    family_a_items = (
        _item("family-a-baseline", content_label=duplicate_content),
        _item("family-a-variant"),
    )
    family_a = ContentFamilyBinding(
        family_id="family-a",
        family_content_sha256=canonical_family_content_sha256(
            [item.content_sha256 for item in family_a_items]
        ),
        baseline_item_id="family-a-baseline",
        items=family_a_items,
    )
    family_b_items = (
        _item("family-b-baseline", content_label=duplicate_content),
        _item("family-b-variant"),
    )
    family_b = ContentFamilyBinding(
        family_id="family-b",
        family_content_sha256=canonical_family_content_sha256(
            [item.content_sha256 for item in family_b_items]
        ),
        baseline_item_id="family-b-baseline",
        items=family_b_items,
    )

    with pytest.raises(
        ValueError,
        match="reference inventory item content hashes must be unique",
    ):
        _inventory(families=(family_a, family_b))


@pytest.mark.parametrize(
    "bad_hash",
    (
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        7,
        None,
    ),
)
def test_content_item_rejects_non_sha256_content_hashes(
    bad_hash: object,
) -> None:
    with pytest.raises(ValueError, match="must be a lowercase SHA-256 digest"):
        ContentItemBinding(
            item_id="item-a",
            content_sha256=bad_hash,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "field",
    (
        "bundle_sha256",
        "source_manifest_sha256",
        "selection_protocol_sha256",
        "selection_commit_sha256",
    ),
)
def test_inventory_rejects_malformed_provenance_hashes(field: str) -> None:
    kwargs: dict[str, object] = {
        "bundle_sha256": _hash("bundle"),
        "source_manifest_sha256": _hash("source-manifest"),
        "source_revision": "release-v1",
        "selection_protocol_sha256": _hash("selection-protocol"),
        "selection_commit_sha256": _hash("selection-commit"),
        "families": (_family("family-a"),),
    }
    kwargs[field] = "A" * 64

    with pytest.raises(ValueError, match="must be a lowercase SHA-256 digest"):
        ReferenceSelectionInventory(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("source_revision", ("", "   ", None, 4))
def test_inventory_requires_nonempty_text_source_revision(
    source_revision: object,
) -> None:
    with pytest.raises(
        ValueError, match="reference source revision must be non-empty text"
    ):
        ReferenceSelectionInventory(
            bundle_sha256=_hash("bundle"),
            source_manifest_sha256=_hash("source-manifest"),
            source_revision=source_revision,  # type: ignore[arg-type]
            selection_protocol_sha256=_hash("selection-protocol"),
            selection_commit_sha256=_hash("selection-commit"),
            families=(_family("family-a"),),
        )


def test_inventory_rejects_empty_families_and_wrong_schema_version() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "reference inventory families must contain " "ContentFamilyBinding records"
        ),
    ):
        _inventory(families=())

    payload = _inventory().to_dict()
    payload["schema_version"] = "arisekit.reference-selection-inventory.v0"
    _rehash_inventory_payload(payload)
    with pytest.raises(
        ValueError, match="unsupported reference selection inventory schema"
    ):
        ReferenceSelectionInventory.from_dict(payload)


@pytest.mark.parametrize(
    ("mutator", "match"),
    (
        (
            lambda payload: payload.pop("source_revision"),
            "reference selection inventory fields are invalid",
        ),
        (
            lambda payload: payload.update({"unexpected": "field"}),
            "reference selection inventory fields are invalid",
        ),
        (
            lambda payload: payload["families"][0].pop("baseline_item_id"),
            "content family binding fields are invalid",
        ),
        (
            lambda payload: payload["families"][0]["items"][0].update(
                {"unexpected": "field"}
            ),
            "content item binding fields are invalid",
        ),
    ),
)
def test_from_dict_rejects_missing_or_unknown_fields(
    mutator: object, match: str
) -> None:
    payload = copy.deepcopy(_inventory().to_dict())
    mutator(payload)  # type: ignore[operator]

    with pytest.raises(ValueError, match=match):
        ReferenceSelectionInventory.from_dict(payload)


def test_from_dict_requires_lists_for_families_and_items() -> None:
    payload = _inventory().to_dict()
    payload["families"] = tuple(payload["families"])
    with pytest.raises(ValueError, match="reference inventory families must be a list"):
        ReferenceSelectionInventory.from_dict(payload)

    payload = _inventory().to_dict()
    payload["families"][0]["items"] = tuple(payload["families"][0]["items"])
    with pytest.raises(ValueError, match="content family items must be a list"):
        ReferenceSelectionInventory.from_dict(payload)


def test_from_json_rejects_duplicate_keys_invalid_roots_and_nonfinite_values() -> None:
    duplicate_key_json = '{"schema_version":"a","schema_version":"b"}'
    with pytest.raises(ValueError, match="duplicate JSON key 'schema_version'"):
        ReferenceSelectionInventory.from_json(duplicate_key_json)

    with pytest.raises(
        ValueError, match="reference selection inventory must contain one JSON object"
    ):
        ReferenceSelectionInventory.from_json("[]")

    with pytest.raises(ValueError, match="non-finite JSON number NaN"):
        ReferenceSelectionInventory.from_json('{"value":NaN}')

    with pytest.raises(
        ValueError, match="reference selection inventory is not valid JSON"
    ):
        ReferenceSelectionInventory.from_json("{")

    with pytest.raises(
        ValueError, match="reference selection inventory must be JSON text"
    ):
        ReferenceSelectionInventory.from_json({"not": "text"})  # type: ignore[arg-type]

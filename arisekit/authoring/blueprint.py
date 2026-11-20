"""Portable authoring contract for NOHARM-style benchmark case families.

These records capture workflow state and provenance. A completed workflow means
that the declared review steps occurred; it is not a certification of clinical
quality, source rights, privacy, or benchmark admission.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from arisekit.common.hashing import strict_canonical_sha256 as _digest
from arisekit.common.jsonio import (
    freeze_json as _freeze_json,
    strict_canonical_json as _canonical_json,
    thaw_json as _thaw_json,
)
from arisekit.common.records import StrictCanonicalRecord
from arisekit.common.validate import sha256_hex as _hash, unique as _unique


SCHEMA_VERSION = "arisekit.benchmark-blueprint.v2"
FIELD_ORIGINS = ("ai_draft", "human_draft", "source_import")
FIELD_STATUSES = ("draft", "clinician_locked")
CASE_REVIEW_STAGES = (
    "draft",
    "clinical_review",
    "clinical_locked",
    "derivative_review",
    "workflow_complete",
)
BLUEPRINT_REVIEW_STAGES = ("draft", "case_review", "workflow_complete")
RIGHTS_BASES = (
    "original",
    "licensed",
    "permission",
    "public_domain",
    "institution_authorized",
    "unknown",
)
RELEASE_SCOPES = ("private", "restricted", "public")
RESPONSE_INSTRUCTION_DELIVERIES = (
    "system_message",
    "user_message_preamble",
)
SPECIALIST_CONSULT_TYPES = ("specialist", "emergency")
SPECIALIST_CONSULT_URGENCIES = ("Urgent", "Routine")
HARM_TYPES = ("omission", "commission")
HARM_SEVERITIES = ("Mild", "Moderate", "Severe")
CANONICAL_NOHARM_PERTURBATIONS_PER_BASE = 10


@dataclass(frozen=True)
class AuthoredText:
    """Text plus its draft origin and clinician-lock state."""

    value: str
    origin: str
    authored_by: str
    status: str = "draft"
    evidence_refs: tuple[str, ...] = ()
    locked_by: str | None = None
    locked_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        _nonempty(self.value, "authored text value")
        _nonempty(self.authored_by, "authored_by")
        _one_of(self.origin, FIELD_ORIGINS, "authored text origin")
        _one_of(self.status, FIELD_STATUSES, "authored text status")
        _string_tuple(self.evidence_refs, "evidence_refs")
        if self.status == "clinician_locked":
            _nonempty(self.locked_by, "locked_by")
            _nonempty(self.locked_at, "locked_at")
        elif self.locked_by is not None or self.locked_at is not None:
            raise ValueError("draft authored text cannot carry lock metadata")

    @classmethod
    def draft(
        cls,
        value: str,
        *,
        authored_by: str,
        origin: str = "ai_draft",
        evidence_refs: Sequence[str] = (),
    ) -> "AuthoredText":
        return cls(
            value=value,
            origin=origin,
            authored_by=authored_by,
            evidence_refs=tuple(evidence_refs),
        )

    def edit(
        self,
        value: str,
        *,
        authored_by: str,
        origin: str = "human_draft",
        evidence_refs: Sequence[str] | None = None,
    ) -> "AuthoredText":
        """Return a new draft. Editing never preserves a prior clinical lock."""
        return AuthoredText.draft(
            value,
            authored_by=authored_by,
            origin=origin,
            evidence_refs=self.evidence_refs if evidence_refs is None else evidence_refs,
        )

    def lock(self, *, clinician: str, at: str) -> "AuthoredText":
        return replace(
            self,
            status="clinician_locked",
            locked_by=clinician,
            locked_at=at,
        )

    def as_draft(self) -> "AuthoredText":
        return replace(self, status="draft", locked_by=None, locked_at=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "origin": self.origin,
            "authored_by": self.authored_by,
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuthoredText":
        return cls(
            value=str(data.get("value", "")),
            origin=str(data.get("origin", "")),
            authored_by=str(data.get("authored_by", "")),
            status=str(data.get("status", "draft")),
            evidence_refs=tuple(data.get("evidence_refs", ())),
            locked_by=_optional_str(data.get("locked_by")),
            locked_at=_optional_str(data.get("locked_at")),
        )


@dataclass(frozen=True)
class SourceRecord:
    """A source locator and recorded rights basis, without certification."""

    id: str
    title: str
    locator: str
    rights_basis: str
    rights_note: str
    recorded_by: str
    recorded_at: str
    content_hash: str | None = None
    license_or_terms: str | None = None
    release_scope: str | None = None
    release_authorization_hash: str | None = None
    release_authorized_by: str | None = None
    release_authorized_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("id", "title", "locator", "rights_note", "recorded_by", "recorded_at"):
            _nonempty(getattr(self, name), f"source {name}")
        _one_of(self.rights_basis, RIGHTS_BASES, "source rights_basis")
        _optional_hash(self.content_hash, "source content_hash")
        release_fields = (
            self.release_scope,
            self.release_authorization_hash,
            self.release_authorized_by,
            self.release_authorized_at,
        )
        if any(value is not None for value in release_fields):
            if any(value is None for value in release_fields):
                raise ValueError(
                    "source release authorization fields must be supplied together"
                )
            _one_of(self.release_scope, RELEASE_SCOPES, "source release_scope")
            _hash(
                self.release_authorization_hash,
                "source release_authorization_hash",
            )
            _nonempty(self.release_authorized_by, "source release_authorized_by")
            _nonempty(self.release_authorized_at, "source release_authorized_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "locator": self.locator,
            "rights_basis": self.rights_basis,
            "rights_note": self.rights_note,
            "recorded_by": self.recorded_by,
            "recorded_at": self.recorded_at,
            "content_hash": self.content_hash,
            "license_or_terms": self.license_or_terms,
            "release_scope": self.release_scope,
            "release_authorization_hash": self.release_authorization_hash,
            "release_authorized_by": self.release_authorized_by,
            "release_authorized_at": self.release_authorized_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceRecord":
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            locator=str(data.get("locator", "")),
            rights_basis=str(data.get("rights_basis", "unknown")),
            rights_note=str(data.get("rights_note", "")),
            recorded_by=str(data.get("recorded_by", "")),
            recorded_at=str(data.get("recorded_at", "")),
            content_hash=_optional_str(data.get("content_hash")),
            license_or_terms=_optional_str(data.get("license_or_terms")),
            release_scope=_optional_str(data.get("release_scope")),
            release_authorization_hash=_optional_str(
                data.get("release_authorization_hash")
            ),
            release_authorized_by=_optional_str(data.get("release_authorized_by")),
            release_authorized_at=_optional_str(data.get("release_authorized_at")),
        )


@dataclass(frozen=True)
class BaseCase:
    presentation: AuthoredText
    reference_recommendations: AuthoredText
    specialty: str
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        _nonempty(self.specialty, "base case specialty")
        _string_tuple(self.source_ids, "base case source_ids")

    def lock(self, *, clinician: str, at: str) -> "BaseCase":
        return replace(
            self,
            presentation=self.presentation.lock(clinician=clinician, at=at),
            reference_recommendations=self.reference_recommendations.lock(
                clinician=clinician, at=at
            ),
        )

    def as_draft(self) -> "BaseCase":
        return replace(
            self,
            presentation=self.presentation.as_draft(),
            reference_recommendations=self.reference_recommendations.as_draft(),
        )

    @property
    def is_locked(self) -> bool:
        return (
            self.presentation.status == "clinician_locked"
            and self.reference_recommendations.status == "clinician_locked"
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "presentation": self.presentation.value,
            "reference_recommendations": self.reference_recommendations.value,
            "specialty": self.specialty,
            "source_ids": list(self.source_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "presentation": self.presentation.to_dict(),
            "reference_recommendations": self.reference_recommendations.to_dict(),
            "specialty": self.specialty,
            "source_ids": list(self.source_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BaseCase":
        return cls(
            presentation=AuthoredText.from_dict(_mapping(data.get("presentation"))),
            reference_recommendations=AuthoredText.from_dict(
                _mapping(data.get("reference_recommendations"))
            ),
            specialty=str(data.get("specialty", "")),
            source_ids=tuple(data.get("source_ids", ())),
        )


@dataclass(frozen=True)
class RubricOption:
    """One atomic clinical action on the NOHARM 1--9 bipolar scale."""

    id: str
    action: AuthoredText
    category: str
    score: int
    depends_on: tuple[str, ...] = ()
    harm_of_inaction: bool = False
    harm_abstraction: str | None = None
    abstraction_type: str | None = None
    source_ids: tuple[str, ...] = ()
    best_in_group: bool = False
    abstraction: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "depends_on", tuple(self.depends_on))
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        _nonempty(self.id, "rubric option id")
        _nonempty(self.category, "rubric option category")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, int)
            or not 1 <= self.score <= 9
        ):
            raise ValueError("rubric option score must be an integer from 1 through 9")
        _string_tuple(self.depends_on, "rubric option depends_on")
        _string_tuple(self.source_ids, "rubric option source_ids")
        if self.id in self.depends_on:
            raise ValueError(f"rubric option {self.id!r} cannot depend on itself")
        if not isinstance(self.harm_of_inaction, bool):
            raise ValueError("rubric option harm_of_inaction must be boolean")
        if not isinstance(self.best_in_group, bool):
            raise ValueError("rubric option best_in_group must be boolean")
        if self.abstraction_type not in (None, "harm", "alternative"):
            raise ValueError("rubric option abstraction_type must be harm, alternative, or null")

        abstraction = self.abstraction
        legacy_abstraction = self.harm_abstraction
        if _has_text(abstraction) and _has_text(legacy_abstraction):
            if abstraction != legacy_abstraction:
                raise ValueError(
                    "rubric option abstraction and harm_abstraction disagree"
                )
        elif _has_text(legacy_abstraction):
            abstraction = legacy_abstraction
        elif _has_text(abstraction):
            if self.abstraction_type == "harm":
                legacy_abstraction = abstraction
        elif abstraction is not None or legacy_abstraction is not None:
            raise ValueError("rubric option abstraction must be non-empty or null")
        object.__setattr__(self, "abstraction", abstraction)
        object.__setattr__(self, "harm_abstraction", legacy_abstraction)

        if (self.abstraction_type is None) != (abstraction is None):
            raise ValueError(
                "rubric option abstraction and abstraction_type must be set together"
            )
        if self.harm_of_inaction:
            if self.abstraction_type != "harm":
                raise ValueError(
                    "harm-of-inaction options require a harm abstraction"
                )
            if self.score > 3:
                raise ValueError(
                    "harm-of-inaction options must use the commission-harm score zone 1-3"
                )

    def lock(self, *, clinician: str, at: str) -> "RubricOption":
        return replace(self, action=self.action.lock(clinician=clinician, at=at))

    def as_draft(self) -> "RubricOption":
        return replace(self, action=self.action.as_draft())

    @property
    def is_locked(self) -> bool:
        return self.action.status == "clinician_locked"

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action.value,
            "category": self.category,
            "score": self.score,
            "depends_on": list(self.depends_on),
            "harm_of_inaction": self.harm_of_inaction,
            "harm_abstraction": self.harm_abstraction,
            "abstraction_type": self.abstraction_type,
            "source_ids": list(self.source_ids),
            "best_in_group": self.best_in_group,
            "abstraction": self.abstraction,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["action"] = self.action.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RubricOption":
        return cls(
            id=str(data.get("id", "")),
            action=AuthoredText.from_dict(_mapping(data.get("action"))),
            category=str(data.get("category", "")),
            score=data.get("score", 0),
            depends_on=tuple(data.get("depends_on", ())),
            harm_of_inaction=data.get("harm_of_inaction", False),
            harm_abstraction=_optional_str(data.get("harm_abstraction")),
            abstraction_type=_optional_str(data.get("abstraction_type")),
            source_ids=tuple(data.get("source_ids", ())),
            best_in_group=data.get("best_in_group", False),
            abstraction=_optional_str(data.get("abstraction")),
        )


@dataclass(frozen=True)
class RubricGroup:
    """A deterministic selection group over atomic rubric options."""

    id: str
    name: str
    option_ids: tuple[str, ...]
    pick_count: int = 1
    pick_rule: str = "exact"

    def __post_init__(self) -> None:
        object.__setattr__(self, "option_ids", tuple(self.option_ids))
        _nonempty(self.id, "rubric group id")
        _nonempty(self.name, "rubric group name")
        _string_tuple(self.option_ids, "rubric group option_ids")
        _unique(self.option_ids, "rubric group option_ids")
        if not self.option_ids:
            raise ValueError("rubric group must contain at least one option")
        if self.pick_rule not in ("exact", "min", "at_most", "at_least"):
            raise ValueError(
                "rubric group pick_rule must be exact, min, at_most, or at_least"
            )
        if (
            isinstance(self.pick_count, bool)
            or not isinstance(self.pick_count, int)
            or self.pick_count < 1
            or self.pick_count > len(self.option_ids)
        ):
            raise ValueError("rubric group pick_count must fit within option_ids")

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "option_ids": list(self.option_ids),
            "pick_count": self.pick_count,
            "pick_rule": self.pick_rule,
        }

    to_dict = semantic_dict

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RubricGroup":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            option_ids=tuple(data.get("option_ids", ())),
            pick_count=data.get("pick_count", 1),
            pick_rule=str(data.get("pick_rule", "exact")),
        )


@dataclass(frozen=True)
class SpecialistConsultRule:
    """A typed consult decision linked to one scored rubric option."""

    consult_type: str
    urgency: str
    option_id: str
    harm_type: str
    harm_severity: str
    specialty: str | None = None

    def __post_init__(self) -> None:
        _one_of(self.consult_type, SPECIALIST_CONSULT_TYPES, "consult type")
        _one_of(self.urgency, SPECIALIST_CONSULT_URGENCIES, "consult urgency")
        _one_of(self.harm_type, HARM_TYPES, "consult harm_type")
        _one_of(self.harm_severity, HARM_SEVERITIES, "consult harm_severity")
        _nonempty(self.option_id, "consult option_id")
        if self.consult_type == "specialist":
            _nonempty(self.specialty, "specialist consult specialty")
        elif self.specialty is not None:
            raise ValueError("emergency consult specialty must be null")
        if self.consult_type == "emergency" and self.urgency != "Urgent":
            raise ValueError("emergency consult urgency must be Urgent")

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "consult_type": self.consult_type,
            "specialty": self.specialty,
            "urgency": self.urgency,
            "option_id": self.option_id,
            "harm_type": self.harm_type,
            "harm_severity": self.harm_severity,
        }

    to_dict = semantic_dict

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecialistConsultRule":
        harm = data.get("harm")
        harm_mapping = _mapping(harm) if harm is not None else {}
        return cls(
            consult_type=str(data.get("consult_type", data.get("type", ""))),
            specialty=_optional_str(data.get("specialty")),
            urgency=str(data.get("urgency", "")),
            option_id=str(data.get("option_id", data.get("optionId", ""))),
            harm_type=str(data.get("harm_type", harm_mapping.get("type", ""))),
            harm_severity=str(
                data.get("harm_severity", harm_mapping.get("severity", ""))
            ),
        )


@dataclass(frozen=True)
class InvarianceAttestation:
    clinical_revision: str
    invariant_components: tuple[str, ...]
    rationale: str
    attested_by: str
    attested_at: str
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "invariant_components", tuple(self.invariant_components))
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        _hash(self.clinical_revision, "attestation clinical_revision")
        _string_tuple(self.invariant_components, "invariant_components")
        if not self.invariant_components:
            raise ValueError("invariance attestation requires at least one invariant component")
        _unique(self.invariant_components, "invariant_components")
        _nonempty(self.rationale, "invariance attestation rationale")
        _nonempty(self.attested_by, "invariance attested_by")
        _nonempty(self.attested_at, "invariance attested_at")
        _string_tuple(self.source_ids, "invariance source_ids")

    def to_dict(self) -> dict[str, Any]:
        return {
            "clinical_revision": self.clinical_revision,
            "invariant_components": list(self.invariant_components),
            "rationale": self.rationale,
            "attested_by": self.attested_by,
            "attested_at": self.attested_at,
            "source_ids": list(self.source_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InvarianceAttestation":
        return cls(
            clinical_revision=str(data.get("clinical_revision", "")),
            invariant_components=tuple(data.get("invariant_components", ())),
            rationale=str(data.get("rationale", "")),
            attested_by=str(data.get("attested_by", "")),
            attested_at=str(data.get("attested_at", "")),
            source_ids=tuple(data.get("source_ids", ())),
        )


@dataclass(frozen=True)
class CaseVariant:
    id: str
    presentation: AuthoredText
    category: str
    changed_dimensions: tuple[str, ...]
    upstream_revision: str
    description: str | None = None
    attestation: InvarianceAttestation | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "changed_dimensions", tuple(self.changed_dimensions))
        _nonempty(self.id, "variant id")
        _nonempty(self.category, "variant category")
        _string_tuple(self.changed_dimensions, "variant changed_dimensions")
        if not self.changed_dimensions:
            raise ValueError("variant must name at least one changed dimension")
        _unique(self.changed_dimensions, "variant changed_dimensions")
        _hash(self.upstream_revision, "variant upstream_revision")
        if self.attestation is not None:
            if self.attestation.clinical_revision != self.upstream_revision:
                raise ValueError("variant attestation does not match its upstream revision")
            if self.presentation.status != "clinician_locked":
                raise ValueError("an attested variant presentation must be clinician locked")
            if (
                self.presentation.locked_by != self.attestation.attested_by
                or self.presentation.locked_at != self.attestation.attested_at
            ):
                raise ValueError(
                    "variant presentation lock must match its attestation actor and time"
                )

    @property
    def is_attested(self) -> bool:
        return self.attestation is not None

    def attest(
        self,
        *,
        clinician: str,
        at: str,
        rationale: str,
        invariant_components: Sequence[str] = ("clinical_truth", "rubric"),
        source_ids: Sequence[str] = (),
    ) -> "CaseVariant":
        attestation = InvarianceAttestation(
            clinical_revision=self.upstream_revision,
            invariant_components=tuple(invariant_components),
            rationale=rationale,
            attested_by=clinician,
            attested_at=at,
            source_ids=tuple(source_ids),
        )
        return replace(
            self,
            presentation=self.presentation.lock(clinician=clinician, at=at),
            attestation=attestation,
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "presentation": self.presentation.value,
            "category": self.category,
            "changed_dimensions": list(self.changed_dimensions),
            "upstream_revision": self.upstream_revision,
            "description": self.description,
            "attestation": self.attestation.to_dict() if self.attestation else None,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["presentation"] = self.presentation.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaseVariant":
        attestation = data.get("attestation")
        return cls(
            id=str(data.get("id", "")),
            presentation=AuthoredText.from_dict(_mapping(data.get("presentation"))),
            category=str(data.get("category", "")),
            changed_dimensions=tuple(data.get("changed_dimensions", ())),
            upstream_revision=str(data.get("upstream_revision", "")),
            description=_optional_str(data.get("description")),
            attestation=(
                InvarianceAttestation.from_dict(_mapping(attestation))
                if attestation is not None
                else None
            ),
        )


@dataclass(frozen=True)
class OptionGuidance:
    """Clinician-reviewable matching notes for one rubric option.

    Aliases and gates use ordered authored-text tuples. This canonicalizes both
    scalar and list-shaped external gate guidance without joining or otherwise
    changing the authored statements.
    """

    option_id: str
    matching: AuthoredText
    disqualifiers: tuple[AuthoredText, ...] = ()
    aliases: tuple[AuthoredText, ...] = ()
    gates: tuple[AuthoredText, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "disqualifiers", tuple(self.disqualifiers))
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "gates", tuple(self.gates))
        _nonempty(self.option_id, "option guidance option_id")

    def lock(self, *, clinician: str, at: str) -> "OptionGuidance":
        return replace(
            self,
            matching=self.matching.lock(clinician=clinician, at=at),
            disqualifiers=tuple(
                item.lock(clinician=clinician, at=at) for item in self.disqualifiers
            ),
            aliases=tuple(
                item.lock(clinician=clinician, at=at) for item in self.aliases
            ),
            gates=tuple(
                item.lock(clinician=clinician, at=at) for item in self.gates
            ),
        )

    @property
    def is_locked(self) -> bool:
        return all(
            item.status == "clinician_locked"
            for item in (
                self.matching,
                *self.disqualifiers,
                *self.aliases,
                *self.gates,
            )
        )

    def semantic_dict(self) -> dict[str, Any]:
        payload = {
            "option_id": self.option_id,
            "matching": self.matching.value,
            "disqualifiers": [item.value for item in self.disqualifiers],
        }
        if self.aliases:
            payload["aliases"] = [item.value for item in self.aliases]
        if self.gates:
            payload["gates"] = [item.value for item in self.gates]
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "option_id": self.option_id,
            "matching": self.matching.to_dict(),
            "disqualifiers": [item.to_dict() for item in self.disqualifiers],
        }
        if self.aliases:
            payload["aliases"] = [item.to_dict() for item in self.aliases]
        if self.gates:
            payload["gates"] = [item.to_dict() for item in self.gates]
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OptionGuidance":
        return cls(
            option_id=str(data.get("option_id", "")),
            matching=AuthoredText.from_dict(_mapping(data.get("matching"))),
            disqualifiers=tuple(
                AuthoredText.from_dict(_mapping(item))
                for item in _sequence(data.get("disqualifiers", ()))
            ),
            aliases=tuple(
                AuthoredText.from_dict(_mapping(item))
                for item in _sequence(data.get("aliases", ()))
            ),
            gates=tuple(
                AuthoredText.from_dict(_mapping(item))
                for item in _sequence(data.get("gates", ()))
            ),
        )


@dataclass(frozen=True)
class GuidanceContract:
    upstream_revision: str
    version: str
    spirit: AuthoredText
    watchouts: tuple[AuthoredText, ...] = ()
    option_rules: tuple[OptionGuidance, ...] = ()
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "watchouts", tuple(self.watchouts))
        object.__setattr__(self, "option_rules", tuple(self.option_rules))
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        _hash(self.upstream_revision, "guidance upstream_revision")
        _nonempty(self.version, "guidance version")
        _unique(tuple(rule.option_id for rule in self.option_rules), "guidance option ids")
        _string_tuple(self.source_ids, "guidance source_ids")
        for rule in self.option_rules:
            for field in (*rule.aliases, *rule.gates):
                if not field.evidence_refs and not self.source_ids:
                    raise ValueError(
                        "guidance aliases and gates require evidence_refs or "
                        "guidance source_ids"
                    )

    @property
    def is_locked(self) -> bool:
        return (
            self.spirit.status == "clinician_locked"
            and all(item.status == "clinician_locked" for item in self.watchouts)
            and all(rule.is_locked for rule in self.option_rules)
        )

    def lock(self, *, clinician: str, at: str) -> "GuidanceContract":
        return replace(
            self,
            spirit=self.spirit.lock(clinician=clinician, at=at),
            watchouts=tuple(
                item.lock(clinician=clinician, at=at) for item in self.watchouts
            ),
            option_rules=tuple(
                rule.lock(clinician=clinician, at=at) for rule in self.option_rules
            ),
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "upstream_revision": self.upstream_revision,
            "version": self.version,
            "spirit": self.spirit.value,
            "watchouts": [item.value for item in self.watchouts],
            "option_rules": [rule.semantic_dict() for rule in self.option_rules],
            "source_ids": list(self.source_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "upstream_revision": self.upstream_revision,
            "version": self.version,
            "spirit": self.spirit.to_dict(),
            "watchouts": [item.to_dict() for item in self.watchouts],
            "option_rules": [rule.to_dict() for rule in self.option_rules],
            "source_ids": list(self.source_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GuidanceContract":
        return cls(
            upstream_revision=str(data.get("upstream_revision", "")),
            version=str(data.get("version", "")),
            spirit=AuthoredText.from_dict(_mapping(data.get("spirit"))),
            watchouts=tuple(
                AuthoredText.from_dict(_mapping(item))
                for item in _sequence(data.get("watchouts", ()))
            ),
            option_rules=tuple(
                OptionGuidance.from_dict(_mapping(item))
                for item in _sequence(data.get("option_rules", ()))
            ),
            source_ids=tuple(data.get("source_ids", ())),
        )


@dataclass(frozen=True)
class NamedHash:
    name: str
    digest: str

    def __post_init__(self) -> None:
        _nonempty(self.name, "named hash name")
        _hash(self.digest, f"named hash {self.name}")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "digest": self.digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NamedHash":
        return cls(name=str(data.get("name", "")), digest=str(data.get("digest", "")))


@dataclass(frozen=True)
class JudgeContract(StrictCanonicalRecord):
    id: str
    version: str
    stages: tuple[str, ...]
    prompt_hashes: tuple[NamedHash, ...]
    schema_hashes: tuple[NamedHash, ...]
    settings: Mapping[str, Any] = field(default_factory=dict)
    partial_credit: bool = True
    runtime_dependency_lock_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stages", tuple(self.stages))
        object.__setattr__(self, "prompt_hashes", tuple(self.prompt_hashes))
        object.__setattr__(self, "schema_hashes", tuple(self.schema_hashes))
        object.__setattr__(self, "settings", _freeze_json(self.settings, "judge settings"))
        _nonempty(self.id, "judge id")
        _nonempty(self.version, "judge version")
        _string_tuple(self.stages, "judge stages")
        if not self.stages:
            raise ValueError("judge contract requires at least one stage")
        _unique(self.stages, "judge stages")
        _unique(tuple(item.name for item in self.prompt_hashes), "judge prompt hash names")
        _unique(tuple(item.name for item in self.schema_hashes), "judge schema hash names")
        _optional_hash(
            self.runtime_dependency_lock_sha256,
            "judge runtime_dependency_lock_sha256",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "stages": list(self.stages),
            "prompt_hashes": [item.to_dict() for item in self.prompt_hashes],
            "schema_hashes": [item.to_dict() for item in self.schema_hashes],
            "settings": _thaw_json(self.settings),
            "partial_credit": self.partial_credit,
            "runtime_dependency_lock_sha256": self.runtime_dependency_lock_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JudgeContract":
        return cls(
            id=str(data.get("id", "")),
            version=str(data.get("version", "")),
            stages=tuple(data.get("stages", ())),
            prompt_hashes=tuple(
                NamedHash.from_dict(_mapping(item))
                for item in _sequence(data.get("prompt_hashes", ()))
            ),
            schema_hashes=tuple(
                NamedHash.from_dict(_mapping(item))
                for item in _sequence(data.get("schema_hashes", ()))
            ),
            settings=_mapping(data.get("settings", {})),
            partial_credit=bool(data.get("partial_credit", True)),
            runtime_dependency_lock_sha256=_optional_str(
                data.get("runtime_dependency_lock_sha256")
            ),
        )


@dataclass(frozen=True)
class AggregationContract(StrictCanonicalRecord):
    primary_metric: str
    base_unit: str
    variant_reduction: str
    trial_reduction: str
    bootstrap_method: str
    bootstrap_iterations: int
    confidence_level: float = 0.95
    weighting: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "weighting", _freeze_json(self.weighting, "aggregation weighting"))
        for name in (
            "primary_metric",
            "base_unit",
            "variant_reduction",
            "trial_reduction",
            "bootstrap_method",
        ):
            _nonempty(getattr(self, name), f"aggregation {name}")
        if (
            isinstance(self.bootstrap_iterations, bool)
            or not isinstance(self.bootstrap_iterations, int)
            or self.bootstrap_iterations < 0
        ):
            raise ValueError("bootstrap_iterations must be a non-negative integer")
        if not isinstance(self.confidence_level, (int, float)) or not 0 < self.confidence_level < 1:
            raise ValueError("confidence_level must be between zero and one")

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_metric": self.primary_metric,
            "base_unit": self.base_unit,
            "variant_reduction": self.variant_reduction,
            "trial_reduction": self.trial_reduction,
            "bootstrap_method": self.bootstrap_method,
            "bootstrap_iterations": self.bootstrap_iterations,
            "confidence_level": self.confidence_level,
            "weighting": _thaw_json(self.weighting),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AggregationContract":
        return cls(
            primary_metric=str(data.get("primary_metric", "")),
            base_unit=str(data.get("base_unit", "")),
            variant_reduction=str(data.get("variant_reduction", "")),
            trial_reduction=str(data.get("trial_reduction", "")),
            bootstrap_method=str(data.get("bootstrap_method", "")),
            bootstrap_iterations=data.get("bootstrap_iterations", 0),
            confidence_level=data.get("confidence_level", 0.95),
            weighting=_mapping(data.get("weighting", {})),
        )


@dataclass(frozen=True)
class ResponseContract(StrictCanonicalRecord):
    system_prompt: str | None
    instructions: str
    required_sections: tuple[str, ...] = ()
    max_words: int | None = None
    instruction_delivery: str = "system_message"

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_sections", tuple(self.required_sections))
        if self.system_prompt is not None:
            _nonempty(self.system_prompt, "response system_prompt")
        _nonempty(self.instructions, "response instructions")
        _one_of(
            self.instruction_delivery,
            RESPONSE_INSTRUCTION_DELIVERIES,
            "response instruction_delivery",
        )
        _string_tuple(self.required_sections, "response required_sections")
        _unique(self.required_sections, "response required_sections")
        if self.max_words is not None and (
            isinstance(self.max_words, bool)
            or not isinstance(self.max_words, int)
            or self.max_words < 1
        ):
            raise ValueError("response max_words must be a positive integer or null")

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "instructions": self.instructions,
            "required_sections": list(self.required_sections),
            "max_words": self.max_words,
            "instruction_delivery": self.instruction_delivery,
        }

    def render_prompts(self, case_prompt: str) -> tuple[str | None, str]:
        """Return the system and user payloads for one case."""
        _nonempty(case_prompt, "case prompt")
        instructions = self.instructions.strip()
        if self.instruction_delivery == "user_message_preamble":
            return self.system_prompt, f"{instructions}\n\n{case_prompt}"
        system_parts = [
            part.strip()
            for part in (self.system_prompt, instructions)
            if part is not None and part.strip()
        ]
        return "\n\n".join(system_parts), case_prompt

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResponseContract":
        return cls(
            system_prompt=_optional_str(data.get("system_prompt")),
            instructions=str(data.get("instructions", "")),
            required_sections=tuple(data.get("required_sections", ())),
            max_words=data.get("max_words"),
            instruction_delivery=str(
                data.get("instruction_delivery", "system_message")
            ),
        )


@dataclass(frozen=True)
class ReviewEvent:
    action: str
    actor: str
    at: str
    revision: str
    note: str | None = None

    def __post_init__(self) -> None:
        for name in ("action", "actor", "at"):
            _nonempty(getattr(self, name), f"review event {name}")
        _hash(self.revision, "review event revision")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "actor": self.actor,
            "at": self.at,
            "revision": self.revision,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewEvent":
        return cls(
            action=str(data.get("action", "")),
            actor=str(data.get("actor", "")),
            at=str(data.get("at", "")),
            revision=str(data.get("revision", "")),
            note=_optional_str(data.get("note")),
        )


@dataclass(frozen=True)
class CaseReviewState:
    stage: str = "draft"
    clinical_locked_revision: str | None = None
    locked_by: str | None = None
    locked_at: str | None = None
    invalidation_reason: str | None = None
    events: tuple[ReviewEvent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        _one_of(self.stage, CASE_REVIEW_STAGES, "case review stage")
        if self.stage in ("clinical_locked", "derivative_review", "workflow_complete"):
            _hash(self.clinical_locked_revision, "clinical_locked_revision")
            _nonempty(self.locked_by, "case review locked_by")
            _nonempty(self.locked_at, "case review locked_at")
        elif any(
            item is not None
            for item in (self.clinical_locked_revision, self.locked_by, self.locked_at)
        ):
            raise ValueError("unlocked case review stages cannot carry clinical lock metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "clinical_locked_revision": self.clinical_locked_revision,
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
            "invalidation_reason": self.invalidation_reason,
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaseReviewState":
        return cls(
            stage=str(data.get("stage", "draft")),
            clinical_locked_revision=_optional_str(data.get("clinical_locked_revision")),
            locked_by=_optional_str(data.get("locked_by")),
            locked_at=_optional_str(data.get("locked_at")),
            invalidation_reason=_optional_str(data.get("invalidation_reason")),
            events=tuple(
                ReviewEvent.from_dict(_mapping(item))
                for item in _sequence(data.get("events", ()))
            ),
        )


@dataclass(frozen=True)
class JudgmentState:
    input_revision: str
    judge_contract_hash: str
    status: str
    recorded_at: str
    artifacts: tuple[NamedHash, ...] = ()
    evaluation_contract_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        _hash(self.input_revision, "judgment input_revision")
        _hash(self.judge_contract_hash, "judgment judge_contract_hash")
        _optional_hash(
            self.evaluation_contract_hash,
            "judgment evaluation_contract_hash",
        )
        _one_of(self.status, ("in_progress", "complete", "failed"), "judgment status")
        _nonempty(self.recorded_at, "judgment recorded_at")
        _unique(tuple(item.name for item in self.artifacts), "judgment artifact names")

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_revision": self.input_revision,
            "judge_contract_hash": self.judge_contract_hash,
            "status": self.status,
            "recorded_at": self.recorded_at,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "evaluation_contract_hash": self.evaluation_contract_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JudgmentState":
        return cls(
            input_revision=str(data.get("input_revision", "")),
            judge_contract_hash=str(data.get("judge_contract_hash", "")),
            status=str(data.get("status", "")),
            recorded_at=str(data.get("recorded_at", "")),
            artifacts=tuple(
                NamedHash.from_dict(_mapping(item))
                for item in _sequence(data.get("artifacts", ()))
            ),
            evaluation_contract_hash=_optional_str(
                data.get("evaluation_contract_hash")
            ),
        )


@dataclass(frozen=True)
class CaseFamily:
    id: str
    base_case: BaseCase
    rubric_options: tuple[RubricOption, ...]
    rubric_groups: tuple[RubricGroup, ...] = ()
    variants: tuple[CaseVariant, ...] = ()
    guidance: GuidanceContract | None = None
    review: CaseReviewState = field(default_factory=CaseReviewState)
    judgment_state: JudgmentState | None = None
    specialist_consults: tuple[SpecialistConsultRule, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rubric_options", tuple(self.rubric_options))
        object.__setattr__(self, "rubric_groups", tuple(self.rubric_groups))
        object.__setattr__(self, "variants", tuple(self.variants))
        object.__setattr__(self, "specialist_consults", tuple(self.specialist_consults))
        self.validate()

    @property
    def clinical_revision(self) -> str:
        return _clinical_revision(
            self.id,
            self.base_case,
            self.rubric_options,
            self.rubric_groups,
            self.specialist_consults,
        )

    @property
    def workflow_revision(self) -> str:
        return _digest(
            {
                "clinical_revision": self.clinical_revision,
                "variants": [variant.semantic_dict() for variant in self.variants],
                "guidance": self.guidance.semantic_dict() if self.guidance else None,
            }
        )

    def validate(self) -> None:
        _nonempty(self.id, "case family id")
        if not self.rubric_options:
            raise ValueError("case family requires at least one rubric option")
        option_ids = tuple(option.id for option in self.rubric_options)
        _unique(option_ids, "case family rubric option ids")
        option_set = set(option_ids)
        for option in self.rubric_options:
            missing = sorted(set(option.depends_on) - option_set)
            if missing:
                raise ValueError(
                    f"rubric option {option.id!r} has unknown dependencies: {', '.join(missing)}"
                )
        _validate_dependency_graph(self.rubric_options)

        group_ids = tuple(group.id for group in self.rubric_groups)
        group_names = tuple(group.name for group in self.rubric_groups)
        _unique(group_ids, "case family rubric group ids")
        _unique(group_names, "case family rubric group names")
        for group in self.rubric_groups:
            missing = sorted(set(group.option_ids) - option_set)
            if missing:
                raise ValueError(
                    f"rubric group {group.id!r} has unknown options: {', '.join(missing)}"
                )

        abstraction_groups: dict[str, RubricGroup] = {}
        for group in self.rubric_groups:
            for reference in (group.id, group.name):
                prior = abstraction_groups.get(reference)
                if prior is not None and prior.id != group.id:
                    raise ValueError(
                        f"rubric group reference {reference!r} is ambiguous"
                    )
                abstraction_groups[reference] = group
        for option in self.rubric_options:
            if option.abstraction_type != "alternative":
                continue
            linked_group = abstraction_groups.get(option.abstraction or "")
            if linked_group is None:
                raise ValueError(
                    f"rubric option {option.id!r} links unknown abstraction group "
                    f"{option.abstraction!r}"
                )
            if option.id not in linked_group.option_ids:
                raise ValueError(
                    f"rubric option {option.id!r} links abstraction group "
                    f"{option.abstraction!r} but is not one of its options"
                )

        _unique(
            tuple(rule.option_id for rule in self.specialist_consults),
            "specialist consult option ids",
        )
        options_by_id = {option.id: option for option in self.rubric_options}
        for rule in self.specialist_consults:
            linked_option = options_by_id.get(rule.option_id)
            if linked_option is None:
                raise ValueError(
                    f"specialist consult references unknown option: {rule.option_id}"
                )
            expected_severity = _consult_harm_severity(
                linked_option.score, rule.harm_type
            )
            if expected_severity != rule.harm_severity:
                raise ValueError(
                    f"specialist consult for option {rule.option_id!r} has severity "
                    f"{rule.harm_severity!r}; score {linked_option.score} and "
                    f"{rule.harm_type} imply {expected_severity!r}"
                )

        variant_ids = tuple(variant.id for variant in self.variants)
        _unique(variant_ids, "case family variant ids")
        for variant in self.variants:
            if variant.upstream_revision != self.clinical_revision:
                raise ValueError(
                    f"variant {variant.id!r} is stale for clinical revision "
                    f"{self.clinical_revision}"
                )

        if self.guidance is not None:
            if self.guidance.upstream_revision != self.clinical_revision:
                raise ValueError("guidance is stale for the current clinical revision")
            unknown = sorted(
                {rule.option_id for rule in self.guidance.option_rules} - option_set
            )
            if unknown:
                raise ValueError(f"guidance references unknown options: {', '.join(unknown)}")

        locked_stage = self.review.stage in (
            "clinical_locked",
            "derivative_review",
            "workflow_complete",
        )
        if locked_stage:
            if self.review.clinical_locked_revision != self.clinical_revision:
                raise ValueError("case review lock is stale for the current clinical revision")
            if not self.base_case.is_locked or not all(
                option.is_locked for option in self.rubric_options
            ):
                raise ValueError("locked case review stage requires all clinical fields locked")
            clinical_fields = (
                self.base_case.presentation,
                self.base_case.reference_recommendations,
                *(option.action for option in self.rubric_options),
            )
            if any(
                field.locked_by != self.review.locked_by
                or field.locked_at != self.review.locked_at
                for field in clinical_fields
            ):
                raise ValueError(
                    "clinical field locks must match the case review actor and time"
                )
            lock_events = tuple(
                event
                for event in self.review.events
                if event.action == "clinician_locked"
            )
            if not lock_events or (
                lock_events[-1].actor != self.review.locked_by
                or lock_events[-1].at != self.review.locked_at
                or lock_events[-1].revision != self.clinical_revision
            ):
                raise ValueError(
                    "case review lock metadata must match its clinician_locked event"
                )
        elif self.variants or self.guidance is not None or self.judgment_state is not None:
            raise ValueError("unlocked clinical drafts cannot carry derivative or judgment state")

        if self.review.stage == "workflow_complete":
            if not self.variants:
                raise ValueError("workflow completion requires at least one case variant")
            if self.guidance is None:
                raise ValueError("workflow completion requires guidance")
            if not all(variant.is_attested for variant in self.variants):
                raise ValueError("workflow completion requires every variant to be attested")
            if not self.guidance.is_locked:
                raise ValueError("workflow completion requires clinician-locked guidance")
            guidance_fields = _guidance_authored_texts(self.guidance)
            guidance_locks = {
                (field.locked_by, field.locked_at) for field in guidance_fields
            }
            if len(guidance_locks) != 1:
                raise ValueError(
                    "all guidance locks must share one clinician actor and time"
                )
            completion_events = tuple(
                event
                for event in self.review.events
                if event.action == "workflow_completed"
            )
            if not completion_events or completion_events[-1].revision != self.workflow_revision:
                raise ValueError(
                    "workflow completion event must bind the current workflow revision"
                )

        if self.judgment_state is not None:
            if self.review.stage != "workflow_complete":
                raise ValueError("judgment state requires a workflow-complete case family")
            if self.judgment_state.input_revision != self.workflow_revision:
                raise ValueError("judgment state is stale for the current workflow revision")

    def submit_clinical_review(
        self, *, actor: str, at: str, note: str | None = None
    ) -> "CaseFamily":
        if self.review.stage != "draft":
            raise ValueError("only a draft case family can enter clinical review")
        event = ReviewEvent(
            action="submitted_clinical_review",
            actor=actor,
            at=at,
            revision=self.clinical_revision,
            note=note,
        )
        review = CaseReviewState(
            stage="clinical_review", events=self.review.events + (event,)
        )
        return replace(self, review=review)

    def lock_clinical(
        self, *, clinician: str, at: str, note: str | None = None
    ) -> "CaseFamily":
        if self.review.stage not in ("draft", "clinical_review"):
            raise ValueError("clinical state can only be locked from draft or clinical review")
        locked_base = self.base_case.lock(clinician=clinician, at=at)
        locked_options = tuple(
            option.lock(clinician=clinician, at=at) for option in self.rubric_options
        )
        revision = _clinical_revision(
            self.id,
            locked_base,
            locked_options,
            self.rubric_groups,
            self.specialist_consults,
        )
        event = ReviewEvent(
            action="clinician_locked",
            actor=clinician,
            at=at,
            revision=revision,
            note=note,
        )
        review = CaseReviewState(
            stage="clinical_locked",
            clinical_locked_revision=revision,
            locked_by=clinician,
            locked_at=at,
            events=self.review.events + (event,),
        )
        return replace(
            self,
            base_case=locked_base,
            rubric_options=locked_options,
            variants=(),
            guidance=None,
            judgment_state=None,
            review=review,
        )

    def edit_clinical(
        self,
        *,
        actor: str,
        at: str,
        base_case: BaseCase | None = None,
        rubric_options: Sequence[RubricOption] | None = None,
        rubric_groups: Sequence[RubricGroup] | None = None,
        specialist_consults: Sequence[SpecialistConsultRule] | None = None,
        note: str | None = None,
    ) -> "CaseFamily":
        """Edit upstream state and invalidate all dependent workflow artifacts."""
        next_base = (base_case or self.base_case).as_draft()
        next_options = tuple(
            option.as_draft()
            for option in (
                self.rubric_options if rubric_options is None else rubric_options
            )
        )
        next_groups = tuple(
            self.rubric_groups if rubric_groups is None else rubric_groups
        )
        next_consults = tuple(
            self.specialist_consults
            if specialist_consults is None
            else specialist_consults
        )
        revision = _clinical_revision(
            self.id, next_base, next_options, next_groups, next_consults
        )
        invalidated = bool(
            self.variants or self.guidance is not None or self.judgment_state is not None
        )
        reason = note or (
            "upstream clinical edit invalidated derivatives and judgments"
            if invalidated
            else "upstream clinical edit"
        )
        event = ReviewEvent(
            action="clinical_edited",
            actor=actor,
            at=at,
            revision=revision,
            note=reason,
        )
        review = CaseReviewState(
            stage="draft",
            invalidation_reason=reason if invalidated else None,
            events=self.review.events + (event,),
        )
        return CaseFamily(
            id=self.id,
            base_case=next_base,
            rubric_options=next_options,
            rubric_groups=next_groups,
            variants=(),
            guidance=None,
            judgment_state=None,
            review=review,
            specialist_consults=next_consults,
        )

    def set_derivatives(
        self,
        *,
        variants: Sequence[CaseVariant],
        guidance: GuidanceContract,
        actor: str,
        at: str,
        note: str | None = None,
    ) -> "CaseFamily":
        if self.review.stage not in (
            "clinical_locked",
            "derivative_review",
            "workflow_complete",
        ):
            raise ValueError("clinical state must be locked before adding derivatives")
        event = ReviewEvent(
            action="derivatives_updated",
            actor=actor,
            at=at,
            revision=self.clinical_revision,
            note=note,
        )
        review = replace(
            self.review,
            stage="derivative_review",
            invalidation_reason=(
                "derivative edit invalidated prior judgments"
                if self.judgment_state is not None
                else None
            ),
            events=self.review.events + (event,),
        )
        return replace(
            self,
            variants=tuple(variants),
            guidance=guidance,
            review=review,
            judgment_state=None,
        )

    def complete_workflow(
        self, *, clinician: str, at: str, note: str | None = None
    ) -> "CaseFamily":
        if self.review.stage != "derivative_review":
            raise ValueError("derivatives must be under review before workflow completion")
        event = ReviewEvent(
            action="workflow_completed",
            actor=clinician,
            at=at,
            revision=self.workflow_revision,
            note=note,
        )
        review = replace(
            self.review,
            stage="workflow_complete",
            invalidation_reason=None,
            events=self.review.events + (event,),
        )
        return replace(self, review=review)

    def record_judgment(self, state: JudgmentState) -> "CaseFamily":
        if self.review.stage != "workflow_complete":
            raise ValueError("judgments can only be recorded for workflow-complete cases")
        if state.input_revision != self.workflow_revision:
            raise ValueError("judgment input_revision does not match the case workflow")
        return replace(self, judgment_state=state)

    def source_ids(self) -> set[str]:
        found = set(self.base_case.source_ids)
        for option in self.rubric_options:
            found.update(option.source_ids)
        for variant in self.variants:
            if variant.attestation:
                found.update(variant.attestation.source_ids)
        if self.guidance:
            found.update(self.guidance.source_ids)
            for field in _guidance_authored_texts(self.guidance):
                found.update(field.evidence_refs)
        return found

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_case": self.base_case.to_dict(),
            "rubric_options": [option.to_dict() for option in self.rubric_options],
            "rubric_groups": [group.to_dict() for group in self.rubric_groups],
            "specialist_consults": [
                rule.to_dict() for rule in self.specialist_consults
            ],
            "variants": [variant.to_dict() for variant in self.variants],
            "guidance": self.guidance.to_dict() if self.guidance else None,
            "review": self.review.to_dict(),
            "judgment_state": (
                self.judgment_state.to_dict() if self.judgment_state else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaseFamily":
        guidance = data.get("guidance")
        judgment = data.get("judgment_state")
        return cls(
            id=str(data.get("id", "")),
            base_case=BaseCase.from_dict(_mapping(data.get("base_case"))),
            rubric_options=tuple(
                RubricOption.from_dict(_mapping(item))
                for item in _sequence(data.get("rubric_options", ()))
            ),
            rubric_groups=tuple(
                RubricGroup.from_dict(_mapping(item))
                for item in _sequence(data.get("rubric_groups", ()))
            ),
            specialist_consults=tuple(
                SpecialistConsultRule.from_dict(_mapping(item))
                for item in _sequence(data.get("specialist_consults", ()))
            ),
            variants=tuple(
                CaseVariant.from_dict(_mapping(item))
                for item in _sequence(data.get("variants", ()))
            ),
            guidance=(
                GuidanceContract.from_dict(_mapping(guidance))
                if guidance is not None
                else None
            ),
            review=CaseReviewState.from_dict(_mapping(data.get("review", {}))),
            judgment_state=(
                JudgmentState.from_dict(_mapping(judgment))
                if judgment is not None
                else None
            ),
        )


@dataclass(frozen=True)
class BenchmarkBlueprint(StrictCanonicalRecord):
    id: str
    name: str
    version: str
    specialty: str
    response_contract: ResponseContract
    judge_contract: JudgeContract
    aggregation_contract: AggregationContract
    sources: tuple[SourceRecord, ...]
    case_families: tuple[CaseFamily, ...]
    review_stage: str = "draft"
    review_events: tuple[ReviewEvent, ...] = ()
    workflow_locked_revision: str | None = None
    schema_version: str = SCHEMA_VERSION
    expected_variants_per_base: int | None = None
    strict_noharm_topology: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "case_families", tuple(self.case_families))
        object.__setattr__(self, "review_events", tuple(self.review_events))
        if not isinstance(self.strict_noharm_topology, bool):
            raise ValueError("strict_noharm_topology must be boolean")
        if self.strict_noharm_topology and self.expected_variants_per_base is None:
            object.__setattr__(
                self,
                "expected_variants_per_base",
                CANONICAL_NOHARM_PERTURBATIONS_PER_BASE,
            )
        self.validate()

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported blueprint schema {self.schema_version!r}; expected {SCHEMA_VERSION!r}"
            )
        for name in ("id", "name", "version", "specialty"):
            _nonempty(getattr(self, name), f"blueprint {name}")
        _one_of(self.review_stage, BLUEPRINT_REVIEW_STAGES, "blueprint review_stage")
        if self.expected_variants_per_base is not None and (
            isinstance(self.expected_variants_per_base, bool)
            or not isinstance(self.expected_variants_per_base, int)
            or self.expected_variants_per_base < 1
        ):
            raise ValueError(
                "expected_variants_per_base must be a positive integer or null"
            )
        if (
            self.strict_noharm_topology
            and self.expected_variants_per_base
            != CANONICAL_NOHARM_PERTURBATIONS_PER_BASE
        ):
            raise ValueError(
                "strict NOHARM topology requires exactly 10 variants per base"
            )
        source_ids = tuple(source.id for source in self.sources)
        family_ids = tuple(family.id for family in self.case_families)
        _unique(source_ids, "blueprint source ids")
        _unique(family_ids, "blueprint case family ids")
        if not self.case_families:
            raise ValueError("blueprint requires at least one case family")
        if (
            self.review_stage == "workflow_complete" or self.strict_noharm_topology
        ) and not self.sources:
            raise ValueError(
                "a complete NOHARM-style blueprint requires a source ledger"
            )
        known_sources = set(source_ids)
        for family in self.case_families:
            unknown = sorted(family.source_ids() - known_sources)
            if unknown:
                raise ValueError(
                    f"case family {family.id!r} references unknown sources: {', '.join(unknown)}"
                )
        if self.review_stage == "workflow_complete" or self.strict_noharm_topology:
            ungrounded = [
                family.id for family in self.case_families if not family.source_ids()
            ]
            if ungrounded:
                raise ValueError(
                    "complete case families must reference source-ledger records: "
                    + ", ".join(ungrounded)
                )
        if self.review_stage == "workflow_complete" and not all(
            family.review.stage == "workflow_complete" for family in self.case_families
        ):
            raise ValueError(
                "blueprint workflow completion requires every case family workflow complete"
            )
        if self.review_stage == "workflow_complete":
            if self.workflow_locked_revision != self.authoring_revision:
                raise ValueError(
                    "blueprint workflow lock is stale for the current authoring revision"
                )
            completion_events = tuple(
                event
                for event in self.review_events
                if event.action == "workflow_completed"
            )
            if (
                not completion_events
                or completion_events[-1].revision != self.authoring_revision
            ):
                raise ValueError(
                    "blueprint workflow event must bind the current authoring revision"
                )
        elif self.workflow_locked_revision is not None:
            raise ValueError(
                "an incomplete blueprint cannot carry a workflow_locked_revision"
            )
        for family in self.case_families:
            judgment = family.judgment_state
            if judgment is None:
                continue
            if judgment.judge_contract_hash != self.judge_contract.digest:
                raise ValueError(
                    f"case family {family.id!r} judgment uses a stale judge contract"
                )
            if judgment.evaluation_contract_hash != self.evaluation_contract_hash:
                raise ValueError(
                    f"case family {family.id!r} judgment uses a stale evaluation contract"
                )
        if self.review_stage == "workflow_complete":
            for family in self.case_families:
                if (
                    self.expected_variants_per_base is not None
                    and len(family.variants) != self.expected_variants_per_base
                ):
                    raise ValueError(
                        f"case family {family.id!r} requires exactly "
                        f"{self.expected_variants_per_base} variants; "
                        f"found {len(family.variants)}"
                    )
                if self.strict_noharm_topology:
                    inaction_count = sum(
                        option.harm_of_inaction
                        for option in family.rubric_options
                    )
                    if inaction_count != 1:
                        raise ValueError(
                            f"strict NOHARM case family {family.id!r} requires "
                            "exactly one harm-of-inaction option"
                        )
        _canonical_json(self.to_dict())

    @property
    def evaluation_contract_hash(self) -> str:
        return _digest(
            {
                "response_contract": self.response_contract.to_dict(),
                "judge_contract": self.judge_contract.to_dict(),
                "aggregation_contract": self.aggregation_contract.to_dict(),
            }
        )

    @property
    def authoring_revision(self) -> str:
        return _digest(
            {
                "id": self.id,
                "name": self.name,
                "version": self.version,
                "specialty": self.specialty,
                "response_contract": self.response_contract.to_dict(),
                "judge_contract": self.judge_contract.to_dict(),
                "aggregation_contract": self.aggregation_contract.to_dict(),
                "sources": [source.to_dict() for source in self.sources],
                "case_families": [family.to_dict() for family in self.case_families],
                "expected_variants_per_base": self.expected_variants_per_base,
                "strict_noharm_topology": self.strict_noharm_topology,
            }
        )

    def with_case_family(
        self, family: CaseFamily, *, actor: str, at: str, note: str | None = None
    ) -> "BenchmarkBlueprint":
        families = list(self.case_families)
        for index, current in enumerate(families):
            if current.id == family.id:
                families[index] = family
                break
        else:
            families.append(family)
        revision = _digest([item.to_dict() for item in families])
        event = ReviewEvent(
            action="case_family_updated",
            actor=actor,
            at=at,
            revision=revision,
            note=note,
        )
        return replace(
            self,
            case_families=tuple(families),
            review_stage="draft",
            workflow_locked_revision=None,
            review_events=self.review_events + (event,),
        )

    def submit_case_review(
        self, *, actor: str, at: str, note: str | None = None
    ) -> "BenchmarkBlueprint":
        if self.review_stage != "draft":
            raise ValueError("only a draft blueprint can enter case review")
        event = ReviewEvent(
            action="submitted_case_review",
            actor=actor,
            at=at,
            revision=self.authoring_revision,
            note=note,
        )
        return replace(
            self,
            review_stage="case_review",
            review_events=self.review_events + (event,),
        )

    def complete_workflow(
        self, *, actor: str, at: str, note: str | None = None
    ) -> "BenchmarkBlueprint":
        if self.review_stage != "case_review":
            raise ValueError("blueprint must be in case review before workflow completion")
        if not all(
            family.review.stage == "workflow_complete" for family in self.case_families
        ):
            raise ValueError("all case-family workflows must be complete")
        event = ReviewEvent(
            action="workflow_completed",
            actor=actor,
            at=at,
            revision=self.authoring_revision,
            note=note,
        )
        return replace(
            self,
            review_stage="workflow_complete",
            workflow_locked_revision=self.authoring_revision,
            review_events=self.review_events + (event,),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "specialty": self.specialty,
            "response_contract": self.response_contract.to_dict(),
            "judge_contract": self.judge_contract.to_dict(),
            "aggregation_contract": self.aggregation_contract.to_dict(),
            "sources": [source.to_dict() for source in self.sources],
            "case_families": [family.to_dict() for family in self.case_families],
            "review_stage": self.review_stage,
            "review_events": [event.to_dict() for event in self.review_events],
            "workflow_locked_revision": self.workflow_locked_revision,
            "expected_variants_per_base": self.expected_variants_per_base,
            "strict_noharm_topology": self.strict_noharm_topology,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkBlueprint":
        if not isinstance(data, Mapping):
            raise ValueError("benchmark blueprint must be a JSON object")
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            specialty=str(data.get("specialty", "")),
            response_contract=ResponseContract.from_dict(
                _mapping(data.get("response_contract"))
            ),
            judge_contract=JudgeContract.from_dict(_mapping(data.get("judge_contract"))),
            aggregation_contract=AggregationContract.from_dict(
                _mapping(data.get("aggregation_contract"))
            ),
            sources=tuple(
                SourceRecord.from_dict(_mapping(item))
                for item in _sequence(data.get("sources", ()))
            ),
            case_families=tuple(
                CaseFamily.from_dict(_mapping(item))
                for item in _sequence(data.get("case_families", ()))
            ),
            review_stage=str(data.get("review_stage", "draft")),
            review_events=tuple(
                ReviewEvent.from_dict(_mapping(item))
                for item in _sequence(data.get("review_events", ()))
            ),
            workflow_locked_revision=_optional_str(
                data.get("workflow_locked_revision")
            ),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            expected_variants_per_base=data.get("expected_variants_per_base"),
            strict_noharm_topology=data.get("strict_noharm_topology", False),
        )


def _clinical_revision(
    family_id: str,
    base_case: BaseCase,
    options: Sequence[RubricOption],
    groups: Sequence[RubricGroup],
    specialist_consults: Sequence[SpecialistConsultRule] = (),
) -> str:
    return _digest(
        {
            "family_id": family_id,
            "base_case": base_case.semantic_dict(),
            "rubric_options": [option.semantic_dict() for option in options],
            "rubric_groups": [group.semantic_dict() for group in groups],
            "specialist_consults": [
                rule.semantic_dict() for rule in specialist_consults
            ],
        }
    )


def _guidance_authored_texts(
    guidance: GuidanceContract,
) -> tuple[AuthoredText, ...]:
    fields: list[AuthoredText] = [guidance.spirit, *guidance.watchouts]
    for rule in guidance.option_rules:
        fields.append(rule.matching)
        fields.extend(rule.disqualifiers)
        fields.extend(rule.aliases)
        fields.extend(rule.gates)
    return tuple(fields)


def _consult_harm_severity(score: int, harm_type: str) -> str:
    if harm_type == "omission":
        severity = {7: "Mild", 8: "Moderate", 9: "Severe"}.get(score)
        zone = "appropriate-action score zone 7-9"
    else:
        severity = {1: "Severe", 2: "Moderate", 3: "Mild"}.get(score)
        zone = "commission-harm score zone 1-3"
    if severity is None:
        raise ValueError(
            f"specialist consult {harm_type} harm must link to the {zone}; got {score}"
        )
    return severity


def _validate_dependency_graph(options: Sequence[RubricOption]) -> None:
    dependencies = {option.id: option.depends_on for option in options}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(option_id: str) -> None:
        if option_id in visiting:
            raise ValueError("rubric option dependencies must not contain a cycle")
        if option_id in visited:
            return
        visiting.add(option_id)
        for dependency in dependencies[option_id]:
            visit(dependency)
        visiting.remove(option_id)
        visited.add(option_id)

    for option_id in dependencies:
        visit(option_id)


def _nonempty(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _one_of(value: Any, choices: Sequence[str], name: str) -> None:
    if value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(choices)}")


def _optional_hash(value: Any, name: str) -> None:
    if value is not None:
        _hash(value, name)


def _string_tuple(values: Sequence[Any], name: str) -> None:
    for value in values:
        _nonempty(value, name)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("expected a JSON object")
    return value


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("expected a JSON array")
    return value


__all__ = [
    "AggregationContract",
    "AuthoredText",
    "BaseCase",
    "BenchmarkBlueprint",
    "CANONICAL_NOHARM_PERTURBATIONS_PER_BASE",
    "CaseFamily",
    "CaseReviewState",
    "CaseVariant",
    "GuidanceContract",
    "InvarianceAttestation",
    "JudgeContract",
    "JudgmentState",
    "NamedHash",
    "OptionGuidance",
    "ResponseContract",
    "ReviewEvent",
    "RubricGroup",
    "RubricOption",
    "SCHEMA_VERSION",
    "SpecialistConsultRule",
    "SourceRecord",
]

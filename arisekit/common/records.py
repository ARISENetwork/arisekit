"""Records identified by the canonical JSON of their to_dict()."""
from __future__ import annotations

from arisekit.common.hashing import canonical_sha256, strict_canonical_sha256
from arisekit.common.jsonio import canonical_json, strict_canonical_json


class CanonicalRecord:
    """A record whose canonical JSON and digest come from its to_dict(); errors as canonical_json."""

    # Empty slots on every parent keep @dataclass(slots=True) records without an instance __dict__.
    __slots__ = ()

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return canonical_sha256(self.to_dict())


class StrictCanonicalRecord(CanonicalRecord):
    """A CanonicalRecord that reports any value it cannot write as a ValueError, as strict_canonical_json."""

    __slots__ = ()

    def canonical_json(self) -> str:
        return strict_canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return strict_canonical_sha256(self.to_dict())


class CanonicalPropertyRecord(CanonicalRecord):
    """A CanonicalRecord whose canonical_json is a property rather than a method."""

    __slots__ = ()

    @property
    def canonical_json(self) -> str:  # type: ignore[override]
        return canonical_json(self.to_dict())


class StrictCanonicalPropertyRecord(StrictCanonicalRecord):
    """A StrictCanonicalRecord whose canonical_json is a property rather than a method."""

    __slots__ = ()

    @property
    def canonical_json(self) -> str:  # type: ignore[override]
        return strict_canonical_json(self.to_dict())

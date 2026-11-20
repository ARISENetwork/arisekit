"""Immutable identity for a reproducible benchmark run.

The manifest records every input that may change which responses belong to a
run. Its canonical JSON representation is hashed and can therefore be used as
a checkpoint namespace without relying on mutable filenames or timestamps.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arisekit.common.jsonio import (
    freeze_json as _freeze_json,
    strict_canonical_json as _canonical_json,
    thaw_json as _thaw_json,
)
from arisekit.common.records import StrictCanonicalRecord


SCHEMA_VERSION = "arisekit.run-manifest.v1"
AUTOMATIC_IDENTITY_VERSION = "arisekit.auto-run-identity.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RunManifest(StrictCanonicalRecord):
    """Frozen inputs for one benchmark-arm and model run.

    Hash fields are lowercase SHA-256 hex digests. ``source_revision`` is kept
    separate because source systems may use another revision format, such as a
    Git commit id. ``seeds`` may be empty when an endpoint does not expose a
    seed, otherwise it contains one seed per trial.
    """

    benchmark_arm: str
    benchmark_content_hash: str
    prompt_hash: str
    code_hash: str
    model: str
    provider: str
    trials: int
    selection: Mapping[str, Any]
    source_revision: str
    rubric_hash: str | None = None
    guidance_hash: str | None = None
    judge_hash: str | None = None
    model_config: Mapping[str, Any] = field(default_factory=dict)
    seeds: tuple[int, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "selection", _freeze_json(self.selection, "selection"))
        object.__setattr__(
            self,
            "model_config",
            _freeze_json(self.model_config, "model_config"),
        )
        object.__setattr__(self, "seeds", tuple(self.seeds))
        self.validate()

    def validate(self) -> None:
        """Raise ``ValueError`` if the manifest cannot identify a valid run."""
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported run manifest schema {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )

        required_strings = (
            "benchmark_arm",
            "model",
            "provider",
            "source_revision",
        )
        for name in required_strings:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"run manifest field {name!r} must be a non-empty string")

        hash_fields = (
            "benchmark_content_hash",
            "prompt_hash",
            "rubric_hash",
            "guidance_hash",
            "judge_hash",
            "code_hash",
        )
        for name in hash_fields:
            value = getattr(self, name)
            if value is None and name in {"rubric_hash", "guidance_hash", "judge_hash"}:
                continue
            if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
                raise ValueError(
                    f"run manifest field {name!r} must be a lowercase SHA-256 hex digest"
                )

        if isinstance(self.trials, bool) or not isinstance(self.trials, int) or self.trials < 1:
            raise ValueError("run manifest trials must be a positive integer")
        if self.seeds and len(self.seeds) != self.trials:
            raise ValueError("run manifest seeds must be empty or contain one seed per trial")
        for seed in self.seeds:
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise ValueError("run manifest seeds must contain integers")

        if not isinstance(self.selection, Mapping):
            raise ValueError("run manifest selection must be a JSON object")
        if not isinstance(self.model_config, Mapping):
            raise ValueError("run manifest model_config must be a JSON object")

        # This also rejects non-finite floats and any value missed by the
        # recursive checks before the digest is used as an identity.
        json.dumps(self.to_dict(), allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-serializable representation."""
        return {
            "schema_version": self.schema_version,
            "benchmark_arm": self.benchmark_arm,
            "benchmark_content_hash": self.benchmark_content_hash,
            "prompt_hash": self.prompt_hash,
            "rubric_hash": self.rubric_hash,
            "guidance_hash": self.guidance_hash,
            "judge_hash": self.judge_hash,
            "code_hash": self.code_hash,
            "model": self.model,
            "provider": self.provider,
            "model_config": _thaw_json(self.model_config),
            "trials": self.trials,
            "seeds": list(self.seeds),
            "selection": _thaw_json(self.selection),
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunManifest":
        """Validate and construct a manifest from parsed JSON."""
        if not isinstance(data, Mapping):
            raise ValueError("run manifest must be a JSON object")
        payload = dict(data)
        try:
            payload["seeds"] = tuple(payload.get("seeds", ()))
            return cls(**payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid run manifest fields: {exc}") from exc


def sha256_digest(value: bytes | str | Mapping[str, Any] | list[Any] | tuple[Any, ...]) -> str:
    """Hash bytes, text, or canonical JSON into lowercase SHA-256 hex."""
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_automatic_run_manifest(
    *,
    benchmark_name: str,
    items: Iterable[Any],
    selected_item_ids: Sequence[str],
    system_prompt: str | None,
    tools: Sequence[Any],
    code_objects: Sequence[Any],
    model: str,
    model_route: str,
    provider: str,
    trials: int,
    limit: int | None,
    model_config: Mapping[str, Any],
) -> RunManifest:
    """Build a conservative content-addressed identity for a local run.

    The helper consumes runtime objects instead of paths supplied by benchmark
    authors. Dataset rows and tool schemas are canonical JSON; executable
    identity hashes the complete source modules for the scorer, tools, and SUT
    objects passed by ``Benchmark.run``. Absolute source paths are never stored
    in the manifest.
    """
    canonical_items = [_item_dict(item) for item in items]
    tool_schemas = [
        {
            "name": str(tool.name),
            "description": str(tool.description),
            "parameters": tool.parameters,
        }
        for tool in tools
    ]
    tool_schema_hash = sha256_digest(tool_schemas)
    config = dict(model_config)
    config["auto_identity_schema"] = AUTOMATIC_IDENTITY_VERSION
    config["route"] = model_route
    config["tool_schema_hash"] = tool_schema_hash

    return RunManifest(
        benchmark_arm=benchmark_name,
        benchmark_content_hash=sha256_digest(canonical_items),
        prompt_hash=sha256_digest(system_prompt or ""),
        code_hash=_source_identity_digest(code_objects),
        model=model,
        provider=provider,
        model_config=config,
        trials=trials,
        selection={
            "limit": limit,
            "item_ids": [str(item_id) for item_id in selected_item_ids],
        },
        source_revision=AUTOMATIC_IDENTITY_VERSION,
    )


def _item_dict(item: Any) -> Mapping[str, Any]:
    to_dict = getattr(item, "to_dict", None)
    if not callable(to_dict):
        raise ValueError("automatic run identity requires items with to_dict()")
    value = to_dict()
    if not isinstance(value, Mapping):
        raise ValueError("automatic run identity item to_dict() must return an object")
    return value


def _source_identity_digest(objects: Sequence[Any]) -> str:
    object_labels: set[str] = set()
    modules: dict[str, str] = {}
    for value in objects:
        target = value if inspect.isclass(value) or inspect.isroutine(value) else type(value)
        module = inspect.getmodule(target)
        if module is None:
            raise ValueError(
                f"cannot identify source module for {_source_object_label(target)}"
            )
        module_name = str(getattr(module, "__name__", "")).strip()
        if not module_name:
            raise ValueError("automatic run identity found an unnamed source module")
        object_labels.add(_source_object_label(target))
        if module_name in modules:
            continue
        try:
            source_path = inspect.getsourcefile(module)
        except TypeError:
            source_path = None
        if source_path is not None and Path(source_path).is_file():
            payload = Path(source_path).read_bytes()
        else:
            try:
                payload = inspect.getsource(module).encode("utf-8")
            except (OSError, TypeError) as exc:
                raise ValueError(
                    f"cannot read source for automatic run identity module {module_name!r}"
                ) from exc
        modules[module_name] = sha256_digest(payload)
    return sha256_digest(
        {
            "identity_schema": AUTOMATIC_IDENTITY_VERSION,
            "objects": sorted(object_labels),
            "modules": dict(sorted(modules.items())),
        }
    )


def _source_object_label(value: Any) -> str:
    module = str(getattr(value, "__module__", ""))
    qualname = str(
        getattr(value, "__qualname__", getattr(value, "__name__", type(value).__name__))
    )
    return f"{module}.{qualname}" if module else qualname


__all__ = [
    "AUTOMATIC_IDENTITY_VERSION",
    "RunManifest",
    "SCHEMA_VERSION",
    "build_automatic_run_manifest",
    "sha256_digest",
]

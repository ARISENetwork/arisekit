"""JSON files, canonical JSON, and JSON objects inside model replies."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any


# JSON files
def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def append_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def json_text(value: Any) -> str:
    """Stored JSON artifacts: two-space indent and a trailing newline."""
    return json.dumps(value, indent=2) + "\n"


# Canonical JSON
def canonical_json(value: Any, *, ensure_ascii: bool = False) -> str:
    """Sorted keys, compact separators, unescaped UTF-8 (escaped ASCII with ensure_ascii), and no NaN or infinity. A
    value that cannot be written raises json.dumps's own TypeError or ValueError."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=ensure_ascii, allow_nan=False)


def strict_canonical_json(value: Any) -> str:
    """canonical_json that reports any value it cannot write as a ValueError."""
    try:
        return canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical JSON: {exc}") from exc


# Read-only JSON values
def freeze_json(value: Any, path: str, *, sort_keys: bool = False) -> Any:
    """A read-only copy of a JSON value: objects become MappingProxyType (keys sorted with sort_keys) and arrays
    tuples. Rejects non-finite floats, non-string keys, and non-JSON types, naming the path."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            frozen[key] = freeze_json(child, f"{path}.{key}", sort_keys=sort_keys)
        return MappingProxyType(dict(sorted(frozen.items())) if sort_keys else frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(child, f"{path}[]", sort_keys=sort_keys) for child in value)
    raise ValueError(f"{path} contains non-JSON value of type {type(value).__name__}")


def freeze(value: Any) -> Any:
    """A read-only copy without validation: mappings become MappingProxyType with str() keys; lists and tuples
    become tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(child) for child in value)
    return value


def thaw_json(value: Any, *, str_keys: bool = False, copy_lists: bool = False) -> Any:
    """Undo freezing: mappings become dicts and tuples lists, recursively. str_keys converts keys with str();
    copy_lists also rebuilds lists, which are otherwise returned as the same object."""
    if isinstance(value, Mapping):
        return {(str(key) if str_keys else key): thaw_json(child, str_keys=str_keys, copy_lists=copy_lists)
                for key, child in value.items()}
    if isinstance(value, tuple) or (copy_lists and isinstance(value, list)):
        return [thaw_json(child, str_keys=str_keys, copy_lists=copy_lists) for child in value]
    return value


def json_copy(value: Any) -> Any:
    """A detached copy through a JSON round trip, keeping key order; errors as json.dumps(allow_nan=False)."""
    return json.loads(json.dumps(value, allow_nan=False))


# Strict JSON
def strict_json_loads(text: Any, label: str, *, finite_floats: bool = False, allow_nan: bool = False,
                      allow_duplicate_keys: bool = False, allow_bytes: bool = False,
                      error: type[ValueError] = ValueError) -> Any:
    """json.loads that rejects duplicate keys and NaN/Infinity. finite_floats also rejects numbers that overflow to
    infinity; allow_nan and allow_duplicate_keys relax the defaults (a duplicate key keeps its last value);
    allow_bytes accepts bytes as well as text. Syntax errors stay json.JSONDecodeError; other rejections raise
    `error`."""
    if not isinstance(text, (str, bytes, bytearray) if allow_bytes else str):
        raise error(f"{label} must be JSON text")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise error(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise error(f"{label} contains non-finite JSON number {value}")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            reject_constant(value)
        return number

    try:
        return json.loads(text, object_pairs_hook=None if allow_duplicate_keys else unique_object,
                          parse_constant=None if allow_nan else reject_constant,
                          parse_float=finite_float if finite_floats else None)
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(f"{label} is not valid JSON: {exc.msg}", exc.doc, exc.pos) from exc


def strict_json_object(text: Any, label: str, **options: Any) -> dict[str, Any]:
    """strict_json_loads that also requires a single JSON object."""
    value = strict_json_loads(text, label, **options)
    if not isinstance(value, dict):
        raise options.get("error", ValueError)(f"{label} must contain one JSON object")
    return value


# Model replies
# A fenced code block in a model reply, optionally labeled json.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _json_body(text: str) -> str:
    """The JSON object in a model reply, tolerating a code fence or surrounding prose."""
    fenced = _FENCE.search(text)
    body = fenced.group(1) if fenced else text
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in model output")
    return body[start:end + 1]


def extract_json(text: str) -> Any:
    return json.loads(_json_body(text))


def outer_json_object(text: str) -> dict[str, Any] | None:
    """The JSON object spanning the reply's first "{" to its last "}", or None when there is none or it is invalid."""
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def duplicate_keys(raw: str) -> list[str]:
    """Keys repeated inside one JSON object of the reply, which json.loads silently collapses."""
    dups: list[str] = []

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [k for k, _ in pairs]
        dups.extend(sorted({k for k in keys if keys.count(k) > 1}))
        return dict(pairs)

    json.loads(_json_body(raw), object_pairs_hook=hook)
    return dups

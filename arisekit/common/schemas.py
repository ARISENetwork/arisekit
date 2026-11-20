"""JSON schemas: provider strict mode, validation errors, and schema identity."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator

from arisekit.common.hashing import sha256


def strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    """A JSON schema object in provider strict mode: every property required, nothing extra."""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a schema to provider strict mode: optional properties become required but nullable."""
    schema = deepcopy(schema)
    schema.pop("$schema", None)
    # Nonempty strings remain enforced by canonical validation after the call.
    schema.pop("minLength", None)
    if "enum" in schema and "type" not in schema:
        schema["type"] = "string"
    if schema.get("type") == "object":
        required = set(schema.get("required", []))
        properties = {key: strict_schema(value) for key, value in schema.get("properties", {}).items()}
        schema["properties"] = {key: value if key in required else nullable(value)
                                for key, value in properties.items()}
        schema["required"] = list(properties)
        schema["additionalProperties"] = False
    elif schema.get("type") == "array":
        schema["items"] = strict_schema(schema["items"])
    return schema


def omit_null_fields(value: Any) -> Any:
    """Undo strict mode's nulls, restoring omission semantics without changing any text."""
    if isinstance(value, dict):
        return {key: omit_null_fields(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [omit_null_fields(item) for item in value]
    return value


def schema_errors(schema: dict[str, Any], value: Any, label: str = "schema") -> list[str]:
    return [f"{label}: {err.message} at {list(err.absolute_path)}" for err in Draft202012Validator(schema).iter_errors(value)]


def schema_sha256(schema: dict[str, Any]) -> str:
    """Identity of a provider-enforced schema, recorded in provenance and compared on resume."""
    return sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")))

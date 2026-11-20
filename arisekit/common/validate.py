"""Value checks shared by record and contract parsers. Each returns the checked value and raises `error`
(ValueError unless the caller passes its own subclass) naming the field."""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any

from arisekit.common.logs import parse_timestamp

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def text(
    value: Any,
    label: str,
    *,
    strip: bool = False,
    no_outer_whitespace: bool = False,
    no_nul: bool = False,
    placeholder: Callable[[str], Any] | None = None,
    error: type[ValueError] = ValueError,
) -> str:
    """Text that is not empty or only whitespace. strip returns it stripped; no_outer_whitespace rejects
    surrounding whitespace; no_nul rejects NUL characters; a truthy placeholder(text) rejects placeholder text,
    checked on the returned text."""
    if not isinstance(value, str) or not value.strip():
        raise error(f"{label} must be non-empty text")
    if no_outer_whitespace and value != value.strip():
        raise error(f"{label} must not have surrounding whitespace")
    if no_nul and "\x00" in value:
        raise error(f"{label} must not contain NUL")
    result = value.strip() if strip else value
    if placeholder is not None and placeholder(result):
        raise error(f"{label} must not be placeholder text")
    return result


def exact_fields(data: Any, expected: set[str], label: str, *, kind: type | None = Mapping,
                 error: type[ValueError] = ValueError) -> None:
    """Require data's keys to be exactly `expected`. data must be an instance of `kind` (Mapping by default); with
    kind=None it is only iterated, as set(data)."""
    if kind is not None and not isinstance(data, kind):
        raise error(f"{label} must be an object")
    actual = set(data)
    if actual != expected:
        raise error(f"{label} fields are invalid: missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}")


def sha256_hex(value: Any, label: str, *, strip: bool = False, error: type[ValueError] = ValueError) -> str:
    """A lowercase hexadecimal SHA-256 digest: exactly 64 characters of 0-9 and a-f. strip removes surrounding
    whitespace first."""
    if strip and isinstance(value, str):
        value = value.strip()
    if not isinstance(value, str) or _SHA256_HEX.fullmatch(value) is None:
        raise error(f"{label} must be a lowercase SHA-256 digest")
    return value


def integer(value: Any, label: str, *, minimum: int | None = None, exact_type: bool = False,
            error: type[ValueError] = ValueError) -> int:
    """An int that is not a bool, at least `minimum` when given; exact_type also rejects int subclasses."""
    valid = type(value) is int if exact_type else isinstance(value, int) and not isinstance(value, bool)
    if not valid or (minimum is not None and value < minimum):
        kind = {None: "an integer", 0: "a nonnegative integer", 1: "a positive integer"}.get(minimum, f"an integer of at least {minimum}")
        raise error(f"{label} must be {kind}")
    return value


def positive_int(value: Any, label: str, *, exact_type: bool = False, error: type[ValueError] = ValueError) -> int:
    return integer(value, label, minimum=1, exact_type=exact_type, error=error)


def nonnegative_int(value: Any, label: str, *, error: type[ValueError] = ValueError) -> int:
    return integer(value, label, minimum=0, error=error)


def number(value: Any, label: str, *, minimum: float | None = None, maximum: float | None = None,
           exclusive_minimum: float | None = None, exclusive_maximum: float | None = None,
           error: type[ValueError] = ValueError) -> float:
    """A finite int or float that is not a bool, returned as a float, within the given bounds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise error(f"{label} must be a finite number")
    if minimum is not None and result < minimum:
        raise error(f"{label} must be at least {minimum}")
    if exclusive_minimum is not None and result <= exclusive_minimum:
        raise error(f"{label} must be greater than {exclusive_minimum}")
    if maximum is not None and result > maximum:
        raise error(f"{label} must be at most {maximum}")
    if exclusive_maximum is not None and result >= exclusive_maximum:
        raise error(f"{label} must be less than {exclusive_maximum}")
    return result


def mapping(value: Any, label: str, *, error: type[ValueError] = ValueError) -> Mapping[str, Any]:
    """A JSON object: any Mapping."""
    if not isinstance(value, Mapping):
        raise error(f"{label} must be an object")
    return value


def array(value: Any, label: str) -> list[Any]:
    """A JSON array: a list."""
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def enum_member(value: Any, enum_type: type[Enum], label: str) -> Any:
    """The enum_type member for value; anything enum_type rejects raises ValueError."""
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be one of {sorted(member.value for member in enum_type)}") from exc


def unique(values: Iterable[Any], label: str, *, key: Callable[[Any], Any] | None = None) -> None:
    """Reject repeated values, or repeated key(value) when key is given."""
    keys = [key(value) for value in values] if key is not None else list(values)
    if len(set(keys)) != len(keys):
        raise ValueError(f"{label} must be unique")


def identifier(value: Any, label: str, pattern: str | re.Pattern[str], *, check_text: Callable[[Any], Any] | None = None,
               max_length: int | None = None, error: type[ValueError] = ValueError) -> str:
    """Text fully matching `pattern`, at most max_length characters when given. check_text, the caller's own text
    check, runs first and its result is what is matched."""
    result = check_text(value) if check_text is not None else value
    if (not isinstance(result, str) or (max_length is not None and len(result) > max_length)
            or re.fullmatch(pattern, result) is None):
        raise error(f"{label} must be a valid identifier")
    return result


def checked_tuple(values: Any, label: str, *, item_type: type | None = None, check: Callable[[Any], Any] | None = None,
                  minimum: int = 0, distinct: bool | str = False) -> tuple[Any, ...]:
    """A tuple from a non-string Sequence, checked in this order: at least `minimum` items; every item an instance of
    item_type; check(item) for every item; and with distinct (True, or "casefold" to ignore case) no repeats."""
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{label} must be a sequence")
    result = tuple(values)
    if len(result) < minimum:
        raise ValueError(f"{label} must contain at least {minimum} values")
    if item_type is not None and any(not isinstance(item, item_type) for item in result):
        raise ValueError(f"{label} contains an invalid value")
    if check is not None:
        for item in result:
            check(item)
    keys = [item.casefold() for item in result] if distinct == "casefold" else result
    if distinct and len(set(keys)) != len(keys):
        raise ValueError(f"{label} must contain unique values")
    return result


def tuple_of(values: Any, item_type: type, label: str) -> tuple[Any, ...]:
    """A tuple whose items are all item_type instances; anything else raises TypeError."""
    if not isinstance(values, tuple):
        raise TypeError(f"{label} must be a tuple")
    if not all(isinstance(item, item_type) for item in values):
        raise TypeError(f"{label} must contain only {item_type.__name__}")
    return values


def timestamp(value: Any, label: str, *, check_text: Callable[[Any], Any] | None = None,
              pattern: str | re.Pattern[str] | None = None) -> datetime:
    """An ISO 8601 timestamp with a timezone, parsed; "Z" means UTC. check_text, the caller's own text check, runs
    first, and the text must then fully match `pattern` when one is given."""
    result = check_text(value) if check_text is not None else value
    if not isinstance(result, str):
        raise ValueError(f"{label} must be a valid ISO 8601 timestamp")
    if pattern is not None and re.fullmatch(pattern, result) is None:
        raise ValueError(f"{label} must be an RFC 3339 timestamp with a timezone")
    try:
        parsed = parse_timestamp(result)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed

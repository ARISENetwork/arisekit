"""UTC timestamps and timestamped progress lines."""
from __future__ import annotations

import sys
from datetime import datetime, timezone


def now_iso(timespec: str = "auto") -> str:
    return datetime.now(timezone.utc).isoformat(timespec=timespec)


def log(msg: str) -> None:
    print(f"{now_iso('seconds')} {msg}", file=sys.stderr)


def parse_timestamp(value: str) -> datetime:
    """datetime.fromisoformat with every "Z" read as UTC ("+00:00")."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

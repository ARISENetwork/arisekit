"""Command-line plumbing: credentials from .env, and argument types that validate user input once against each
module's own rules."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from pipeline.e2e.constants import ENV_PATH
from pipeline.e2e.project import NAMES, REVIEWED_LABEL, RUN_LABEL


def load_env() -> None:
    """Read the kit's .env; variables already exported in the shell win."""
    load_dotenv(ENV_PATH, override=False)


def require(name: str) -> str:
    """A required credential, with a message that says how to set it."""
    if not (value := os.environ.get(name, "")):
        raise RuntimeError(f"{name} is not set. Add it to {ENV_PATH} or export it in your shell.")
    return value


def _name(kind: str, value: str) -> str:
    pattern, description = NAMES[kind]
    if not re.fullmatch(pattern, value):
        raise argparse.ArgumentTypeError(f"{kind} must be {description}, got {value!r}")
    return value


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return number


def new_project(value: str) -> Path:
    """A folder for a new project; its name becomes the project name."""
    path = Path(value)
    _name("project name", path.name)
    return path


def case_id(value: str) -> str:
    if _name("case id", value).startswith("Ex"):
        raise argparse.ArgumentTypeError("case id cannot use the reserved Ex prefix")
    return value


def rubric_label(value: str) -> str:
    if not (RUN_LABEL.fullmatch(value) or REVIEWED_LABEL.fullmatch(value)):
        raise argparse.ArgumentTypeError(f"rubric must be 'run<k>' or 'reviewed-<reviewer>', got {value!r}")
    return value


def rating_tag(value: str) -> str:
    return _name("rating tag", value)

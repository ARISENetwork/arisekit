"""Saved response prompts and the identity of prompted response sets."""
from __future__ import annotations

import re

from arisekit.common.hashing import sha256
from arisekit.common.jsonio import read_json

from pipeline.e2e.project import Project

UNPROMPTED_SHA256 = sha256("")
PROMPT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FIELDS = ("id", "name", "text", "sha256", "savedAt")


def prompt_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def set_id(model: str, prompt: str | None) -> str:
    return model if prompt is None else f"{model}+{prompt}"


def load_prompts(project: Project) -> dict[str, dict]:
    path = project.root / "prompts.json"
    if not path.exists():
        return {}
    try:
        data = read_json(path)
        entries = data["prompts"]
        prompts: dict[str, dict] = {}
        for entry in entries:
            missing = [f for f in FIELDS if not isinstance(entry.get(f), str)]
            if missing:
                raise ValueError(f"prompt {entry.get('id')!r} is missing {', '.join(missing)}")
            if not PROMPT_ID.match(entry["id"]):
                raise ValueError(f"invalid prompt id {entry['id']!r}")
            if entry["id"] in prompts:
                raise ValueError(f"duplicate prompt id {entry['id']!r}")
            if sha256(entry["text"]) != entry["sha256"]:
                raise ValueError(f"prompt {entry['id']!r} text does not match its recorded sha256")
            prompts[entry["id"]] = entry
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"malformed prompts.json: {error!r}") from error
    return prompts


def set_prompt(project: Project, set_name: str) -> dict | None:
    return project.provenance().get("inference", {}).get("set_prompts", {}).get(set_name)


def set_template(project: Project, set_name: str, legacy_template: str) -> str:
    """Saved text for a set declared in set_prompts; any other set is unprompted. A new run takes its template from load_prompts."""
    recorded = set_prompt(project, set_name)
    if recorded is None:
        return legacy_template
    prompt = load_prompts(project).get(recorded["id"])
    if prompt is None:
        raise ValueError(f"prompt {recorded['id']!r} is missing from prompts.json")
    if prompt["sha256"] != recorded["sha256"]:
        raise ValueError(f"prompt {recorded['id']!r} changed after responses were collected")
    return prompt["text"]


def used_prompts(project: Project) -> set[str]:
    return {entry["id"] for entry in project.provenance().get("inference", {}).get("set_prompts", {}).values()}

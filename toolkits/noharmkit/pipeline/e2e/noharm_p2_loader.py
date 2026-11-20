"""Load the unmodified current-grading scorer and F1 modules without changing the toolkit's tools namespace."""
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
from threading import Lock
from types import ModuleType, SimpleNamespace
from typing import Any

from pipeline.e2e.constants import KIT_ROOT

SOURCE_COMMIT = "c4c8091c486bd18fb83e76860c49f8d4b1666993"
ROOT = KIT_ROOT / "vendor/noharm-science/c4c8091c4"
FREEZE_DIR = ROOT / "experiments/freeze/pipeline-v1"
PAYLOAD = {
    "tools/score_rubric.py",
    "tools/score_text_rubric.py",
    "tools/score_text_rubric_v2.py",
    "tools/score_text_rubric_f1.py",
    "experiments/profiles/text-rubric-v2/judge/schema.json",
    "experiments/freeze/pipeline-v1/config.json",
    "experiments/freeze/pipeline-v1/manifest.json",
    "experiments/freeze/pipeline-v1/judge/prompt.md",
    "experiments/freeze/pipeline-v1/judge/rules.md",
    "experiments/freeze/pipeline-v1/review/second.md",
    "experiments/freeze/pipeline-v1/review/severe3.md",
    "experiments/freeze/pipeline-v2/manifest.json",
}
_MODULES = ("score_rubric", "score_text_rubric", "score_text_rubric_v2", "score_text_rubric_f1")
_LOADED: SimpleNamespace | None = None
_LOCK = Lock()


def _verified_payload() -> dict[str, bytes]:
    provenance = json.loads((ROOT / "PROVENANCE.json").read_text())
    if provenance["commit"] != SOURCE_COMMIT or set(provenance["sha256"]) != PAYLOAD:
        raise ValueError("Current grading: provenance does not match the pinned code snapshot")
    payload = {}
    for name in sorted(PAYLOAD):
        content = (ROOT / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != provenance["sha256"][name]:
            raise ValueError(f"Current grading: snapshot hash differs: {name}")
        payload[name] = content
    return payload


def load() -> SimpleNamespace:
    global _LOADED
    with _LOCK:
        if _LOADED is not None:
            return _LOADED
        payload = _verified_payload()
        dependencies = ModuleType("_noharm_p2_tools")

        def private_import(name: str, globals: dict[str, Any] | None = None,
                           locals: dict[str, Any] | None = None,
                           fromlist: tuple[str, ...] = (), level: int = 0) -> Any:
            if level == 0 and name == "tools" and fromlist:
                if any(value not in set(_MODULES[:3]) for value in fromlist):
                    raise ImportError("Unsupported import from the private NOHARM tools namespace")
                return dependencies
            return builtins.__import__(name, globals, locals, fromlist, level)

        for name in _MODULES:
            path = ROOT / "tools" / f"{name}.py"
            spec = importlib.util.spec_from_file_location(f"_noharm_p2_tools.{name}", path)
            if spec is None:
                raise ImportError(f"Cannot load the pinned NOHARM module: {name}")
            module = importlib.util.module_from_spec(spec)
            # Remap only upstream's absolute sibling imports; toolkit imports stay untouched.
            module.__dict__["__builtins__"] = {**vars(builtins), "__import__": private_import}
            exec(compile(payload[f"tools/{name}.py"], str(path), "exec"), module.__dict__)
            setattr(dependencies, name, module)
        v2 = dependencies.score_text_rubric_v2
        if v2.ROOT != ROOT:
            raise ImportError("The pinned NOHARM scorer resolved a different snapshot root")
        _LOADED = SimpleNamespace(v2=v2, f1=dependencies.score_text_rubric_f1)
        return _LOADED

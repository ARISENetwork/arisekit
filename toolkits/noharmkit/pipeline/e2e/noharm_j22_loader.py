"""Load the unmodified snapshot of the earlier judge rules and scorer without changing the toolkit's tools namespace."""
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
from threading import Lock
from types import ModuleType
from typing import Any

from pipeline.e2e.constants import KIT_ROOT

SOURCE_COMMIT = "d734383670f0e8251f46fc3e800038f2a46db0d6"
ROOT = KIT_ROOT / "vendor/noharm-science/d734383670f0"
PAYLOAD = {
    "tools/score_rubric.py",
    "tools/score_text_rubric.py",
    "tools/score_text_rubric_v2.py",
    "experiments/profiles/text-rubric-v2/judge/schema.json",
    "experiments/analyses/20261025-v34-e2e/judge-j2/prompt.md",
    "experiments/analyses/20261025-v34-e2e/judge-j2/rules.md",
    "experiments/analyses/20261025-v34-e2e/judge-j2/schema.json",
}
_SCORER: ModuleType | None = None
_LOCK = Lock()


def _verified_payload() -> dict[str, bytes]:
    provenance = json.loads((ROOT / "PROVENANCE.json").read_text())
    if provenance["commit"] != SOURCE_COMMIT or set(provenance["sha256"]) != PAYLOAD:
        raise ValueError("Earlier judge rules and scorer: provenance does not match the pinned code snapshot")
    payload = {}
    for name in sorted(PAYLOAD):
        content = (ROOT / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != provenance["sha256"][name]:
            raise ValueError(f"Earlier judge rules and scorer: snapshot hash differs: {name}")
        payload[name] = content
    return payload


def load_scorer() -> ModuleType:
    global _SCORER
    with _LOCK:
        if _SCORER is not None:
            return _SCORER
        payload = _verified_payload()
        dependencies = ModuleType("_noharm_j22_tools")

        def private_import(name: str, globals: dict[str, Any] | None = None,
                           locals: dict[str, Any] | None = None,
                           fromlist: tuple[str, ...] = (), level: int = 0) -> Any:
            if level == 0 and name == "tools" and fromlist:
                if any(value not in {"score_rubric", "score_text_rubric"} for value in fromlist):
                    raise ImportError("Unsupported import from the private NOHARM tools namespace")
                return dependencies
            return builtins.__import__(name, globals, locals, fromlist, level)

        for name in ("score_rubric", "score_text_rubric", "score_text_rubric_v2"):
            path = ROOT / "tools" / f"{name}.py"
            spec = importlib.util.spec_from_file_location(f"_noharm_j22_tools.{name}", path)
            if spec is None:
                raise ImportError(f"Cannot load the pinned NOHARM module: {name}")
            module = importlib.util.module_from_spec(spec)
            # Remap only upstream's absolute sibling imports; toolkit imports stay untouched.
            module.__dict__["__builtins__"] = {**vars(builtins), "__import__": private_import}
            exec(compile(payload[f"tools/{name}.py"], str(path), "exec"), module.__dict__)
            setattr(dependencies, name, module)
        scorer = dependencies.score_text_rubric_v2
        if scorer.ROOT != ROOT:
            raise ImportError("The pinned NOHARM scorer resolved a different snapshot root")
        _SCORER = scorer
        return scorer

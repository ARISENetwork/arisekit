"""`noharm view`: the local project viewer."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from pipeline.e2e.constants import APP_ROOT


def listener(port: int) -> str | None:
    """What is listening on the port (lsof's report), or None when the port is free."""
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return None
    found = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                           capture_output=True, text=True, check=False).stdout.strip()
    return found or f"an unidentified process accepts connections on port {port}"


def view_env(projects: Path, origins: list[str], base: Mapping[str, str]) -> dict[str, str]:
    """The app's environment: the chosen projects folder under both its current and legacy names."""
    root = str(projects.resolve())
    env = {**base, "NOHARM_PROJECTS": root, "NOHARM_CASESETS": root, "NOHARM_DEV_ORIGINS": ",".join(origins)}
    env.pop("NOHARM_DEV", None)
    return env


def serve(projects: Path, port: int) -> int:
    if not projects.is_dir():
        print(f"{projects}: no such project storage folder", file=sys.stderr)
        return 1
    if (who := listener(port)) is not None:
        print(f"port {port} is in use; stop that process or pass --port:\n{who}", file=sys.stderr)
        return 1
    next_bin = APP_ROOT / "node_modules" / ".bin" / "next"
    if not next_bin.exists():
        print(f"{next_bin} is missing; run `npm ci` in app/ first", file=sys.stderr)
        return 1
    env = view_env(projects, ["localhost"], os.environ)
    command = [str(next_bin), "dev", "--hostname", "127.0.0.1", "--port", str(port)]
    try:
        build = subprocess.call(["npm", "run", "build:portable"], cwd=APP_ROOT, env=env)
        if build:
            return build
        print(f"http://localhost:{port}/", flush=True)
        return subprocess.call(command, cwd=APP_ROOT, env=env)
    except KeyboardInterrupt:
        return 130

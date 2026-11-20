"""Repository paths."""
from __future__ import annotations

from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = KIT_ROOT / "app"
SKILLS_ROOT = KIT_ROOT / "skills"
ENV_PATH = KIT_ROOT / ".env"

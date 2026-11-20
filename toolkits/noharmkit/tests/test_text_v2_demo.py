from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.e2e import text_v2_runtime
from pipeline.e2e.project import Project




def test_pinned_text_v2_import_has_no_unrecorded_drift() -> None:
    from tools.check_text_v2_upstream import check
    assert check() == []

import base64
import io
import json
from pathlib import Path
import stat
import threading
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
import zipfile

import pytest

from arisekit.launcher import LocalLauncher, extract_authoring, make_launcher_server

AUTHORING = Path(__file__).parents[1] / "examples/agentic-fhir-golden-path/authoring"


def bundle(extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for path in AUTHORING.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(AUTHORING))
        if extra:
            archive.writestr(*extra)
    return stream.getvalue()


@pytest.fixture
def launcher(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html>workspace</html>")
    value = LocalLauncher(tmp_path / "projects", ui)
    yield value
    value.close()


def test_open_resume_and_smoke_use_reviewed_bundle_without_paid_inference(launcher, monkeypatch):
    import litellm
    no_calls = Mock(side_effect=AssertionError("unexpected inference"))
    monkeypatch.setattr(litellm, "completion", no_calls)
    url = launcher.open_bundle(bundle(), {})
    parts = urlsplit(url)
    headers = {"Authorization": "Bearer " + parse_qs(parts.fragment)["token"][0], "Content-Type": "application/json"}
    endpoint = f"http://{parts.netloc}/api/workspace"
    with urlopen(Request(endpoint, headers=headers)) as response:
        assert json.load(response)["readiness"] == "awaiting_smoke_test"
    with urlopen(Request(endpoint + "/smoke", data=b'{"confirm_paid":true}', headers=headers)) as response:
        assert response.status == 202
    # The job API reports progress; wait for the worker to finish, then reopen its retained files.
    import time
    for _ in range(100):
        with urlopen(Request(endpoint + "/jobs", headers=headers)) as response:
            jobs = json.load(response)
        if all(job["status"] != "running" for job in jobs):
            break
        time.sleep(0.02)
    assert jobs[0]["status"] == "complete"
    launcher.close()
    launcher.worker = None
    resumed = urlsplit(launcher.open_bundle(bundle(), {}))
    with urlopen(Request(f"http://{resumed.netloc}/api/workspace", headers={"Authorization": "Bearer " + parse_qs(resumed.fragment)["token"][0]})) as response:
        snapshot = json.load(response)
    assert snapshot["readiness"] == "ready"
    assert snapshot["runs"][0]["bundle"]["summary"]["completed"] > 0
    assert len(list(launcher.root.iterdir())) == 1
    no_calls.assert_not_called()


@pytest.mark.parametrize("path", ["../outside.json", "/absolute.json", "data/../../outside.json", "data\\outside.json", "./alias.json", "BENCHMARK-BUILD-SPEC.JSON", "evil.py", "NUL.json", "data./file.json"])
def test_unsafe_bundle_members_are_rejected_before_writing(tmp_path, path):
    with pytest.raises(ValueError):
        extract_authoring(bundle((path, "{}")), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_symlink_and_corrupt_source_rejected(launcher):
    link = zipfile.ZipInfo("link.json")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError):
        launcher.open_bundle(bundle((link, "target")), {})
    source = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle())) as original, zipfile.ZipFile(source, "w") as changed:
        for row in original.infolist():
            changed.writestr(row, b"{}\n" if row.filename.endswith(".jsonl") else original.read(row))
    with pytest.raises(ValueError, match="SHA-256|hash"):
        launcher.open_bundle(source.getvalue(), {})
    assert list(launcher.root.iterdir()) == []


def test_setup_http_rejects_missing_token_foreign_origin_and_arbitrary_settings(launcher):
    server, url = make_launcher_server(launcher)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    parts = urlsplit(url)
    endpoint = f"http://{parts.netloc}/open"
    token = parse_qs(parts.fragment)["token"][0]
    payload = json.dumps({"archive": base64.b64encode(bundle()).decode(), "credentials": {"PYTHONPATH": "/tmp"}}).encode()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    try:
        for overrides in [{"Authorization": ""}, {"Origin": "https://outside.example"}, {"Host": "rebind.example"}]:
            with pytest.raises(HTTPError) as error:
                urlopen(Request(endpoint, data=payload, headers={**headers, **overrides}), timeout=3)
            assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            urlopen(Request(endpoint, data=payload, headers=headers), timeout=3)
        assert error.value.code == 400
        assert launcher.worker is None
    finally:
        server.shutdown()
        server.server_close()


def test_provider_key_is_not_written_to_project_or_receipts(launcher, monkeypatch):
    import os
    monkeypatch.setenv("OPENROUTER_API_KEY", "before-test")
    marker = "synthetic-test-key-not-a-real-secret"
    launcher.open_bundle(bundle(), {"OPENROUTER_API_KEY": marker})
    assert os.environ["OPENROUTER_API_KEY"] == marker
    for path in launcher.root.rglob("*"):
        if path.is_file():
            assert marker.encode() not in path.read_bytes()

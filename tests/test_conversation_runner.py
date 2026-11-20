import base64
import io
import json
import threading
import time
import zipfile
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import pytest

from arisekit.launcher import LocalLauncher, make_launcher_server
from test_launcher import bundle

CHAT = "http://127.0.0.1:5181"


@pytest.fixture
def service(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("workspace")
    launcher = LocalLauncher(tmp_path / "saved", ui)
    server, link = make_launcher_server(launcher, chat_url=CHAT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    parsed = urlsplit(link)
    token = parse_qs(parsed.fragment)["token"][0]
    base = f"http://{parsed.netloc}"

    def request(path, payload=None, *, headers=None, method=None):
        req = Request(base + path, data=None if payload is None else json.dumps(payload).encode(), headers={"Authorization": f"Bearer {token}", "Origin": CHAT, "Content-Type": "application/json", **(headers or {})}, method=method)
        return urlopen(req, timeout=5)

    yield launcher, request, base, token
    server.shutdown()
    server.server_close()
    launcher.close()


def save(request, data=None, name="First version"):
    with request("/api/benchmarks", {"name": name, "archive": base64.b64encode(data or bundle()).decode()}) as response:
        assert response.status == 201
        return json.load(response)


def test_save_run_resume_reopen_and_download_in_one_connection(service):
    launcher, request, _, _ = service
    saved = save(request)
    identifier = saved["id"]
    endpoint = f"/api/benchmarks/{identifier}/workspace"
    with request(endpoint + "/smoke", {"confirm_paid": True}) as response:
        assert response.status == 202
    for _ in range(150):
        with request(endpoint + "/jobs") as response:
            jobs = json.load(response)
        if jobs and jobs[0]["status"] != "running":
            break
        time.sleep(.02)
    assert jobs[0]["status"] == "complete", jobs
    with request(endpoint) as response:
        complete = json.load(response)
    assert complete["runs"][0]["bundle"]["summary"]["completed"] > 0
    assert save(request, name="Same bytes again")["id"] == identifier
    assert save(request, name="Same bytes again")["name"] == "First version"
    restored = LocalLauncher(launcher.root, launcher.ui)
    assert restored.saved_versions() == [saved]
    assert restored.workspace(identifier).snapshot()["readiness"] == "ready"
    with request(f"/api/benchmarks/{identifier}/bundle") as response:
        downloaded = response.read()
    with zipfile.ZipFile(io.BytesIO(downloaded)) as archive:
        assert "benchmark-build-spec.json" in archive.namelist()
    with request(endpoint + "/sweep", {"models": [complete["smoke_test"]["model"]], "confirm_paid": True}) as response:
        assert response.status == 202
    for _ in range(150):
        with request(endpoint + "/jobs") as response:
            jobs = json.load(response)
        if all(job["status"] != "running" for job in jobs):
            break
        time.sleep(.02)
    with request(endpoint + "/sweep", {"models": [complete["smoke_test"]["model"]], "confirm_paid": True}) as response:
        assert response.status == 202
    for _ in range(150):
        with request(endpoint + "/jobs") as response:
            jobs = json.load(response)
        if all(job["status"] != "running" for job in jobs):
            break
        time.sleep(.02)
    with request(endpoint) as response:
        runs = json.load(response)["runs"]
    assert any(run["bundle"]["summary"]["skipped"] > 0 for run in runs)


def test_changed_plan_is_a_distinct_saved_version(service):
    launcher, request, _, _ = service
    first = save(request)
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle())) as source, zipfile.ZipFile(changed, "w") as target:
        for entry in source.infolist():
            data = source.read(entry)
            if entry.filename == "benchmark-build-spec.json":
                spec = json.loads(data)
                spec["benchmark"]["name"] = "A revised benchmark name"
                data = json.dumps(spec).encode()
            target.writestr(entry, data)
    second = save(request, changed.getvalue(), "Second version")
    assert first["id"] != second["id"]
    assert {v["name"] for v in launcher.saved_versions()} == {"First version", "Second version"}


def test_runner_origin_token_and_path_boundaries(service):
    _, request, base, token = service
    with request("/api/benchmarks", method="OPTIONS", headers={"Authorization": ""}) as response:
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == CHAT
        assert response.headers["Access-Control-Allow-Private-Network"] == "true"
    for headers in [{"Authorization": ""}, {"Origin": "https://evil.example"}, {"Host": "rebind.example"}]:
        with pytest.raises(HTTPError) as error:
            request("/api/benchmarks", headers=headers)
        assert error.value.code == 403
    with urlopen(base) as response:
        assert token.encode() not in response.read()
    with pytest.raises(HTTPError) as error:
        request("/api/benchmarks/../../workspace")
    assert error.value.code == 422
    with pytest.raises(HTTPError) as error:
        request("/connection", {"credentials": {"OPENROUTER_API_KEY": "never-store-this"}})
    assert error.value.code == 403


def test_tampered_saved_plan_cannot_be_reopened(service):
    launcher, request, _, _ = service
    saved = save(request)
    (launcher.root / saved["id"] / "authoring" / "benchmark-build-spec.json").write_text("{}")
    with pytest.raises(ValueError, match="does not match"):
        LocalLauncher(launcher.root, launcher.ui).workspace(saved["id"])
    with pytest.raises(HTTPError):
        request(f'/api/benchmarks/{saved["id"]}/workspace')


def test_chat_destination_changes_only_from_authenticated_local_setup_and_survives_restart(service):
    launcher, request, base, token = service
    destination = "http://127.0.0.1:5180/benchmark/stage/needs-analysis"
    for headers in [{}, {"Origin": base, "Authorization": ""}, {"Origin": "https://evil.example"}]:
        with pytest.raises(HTTPError) as error:
            request("/chat", {"url": destination}, headers=headers)
        assert error.value.code == 403
    for bad in ["http://evil.example/benchmark", "https://user:pass@example.org", destination + "#token=secret", "javascript:alert(1)", destination + "?token=secret", "https://example.org:invalid"]:
        with pytest.raises(HTTPError) as error:
            request("/chat", {"url": bad}, headers={"Origin": base})
        assert error.value.code == 400
    with request("/chat", {"url": destination}, headers={"Origin": base}) as response:
        assert json.load(response)["url"] == destination
    assert LocalLauncher(launcher.root, launcher.ui).saved_chat_url() == destination
    with request("/api/benchmarks", headers={"Origin": "http://127.0.0.1:5180"}) as response:
        assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5180"
        assert json.load(response) == []
    with pytest.raises(HTTPError) as error:
        request("/api/benchmarks")
    assert error.value.code == 403
    with urlopen(base) as response:
        page = response.read().decode()
    assert destination in page
    assert token not in page
    assert 'id="copy-runner"' in page
    assert "navigator.clipboard.writeText(runnerLink.value)" in page
    assert "showRunnerLink();status('provider-status','Provider settings saved.')" in page

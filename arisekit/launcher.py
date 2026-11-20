"""Browser setup for a local, reviewed public/synthetic authoring bundle."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
import stat
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath

from arisekit.runtime.runner_setup import SETUP_HTML
from arisekit.scaffold import BenchmarkScaffoldSpec, scaffold_benchmark
from arisekit.workspace import ResultsWorkspace, make_server

MAX_ARCHIVE = 64 * 1024 * 1024
CREDENTIALS = {"OPENROUTER_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION", "AZURE_AD_TOKEN"}


def extract_authoring(data: bytes, destination: Path) -> None:
    """Accept data-only exports; never extract executable files or path aliases."""
    if len(data) > MAX_ARCHIVE:
        raise ValueError("Authoring bundles must be at most 64 MiB")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= 2000 or sum(row.file_size for row in members) > MAX_ARCHIVE:
            raise ValueError("The bundle has too many files or exceeds 64 MiB expanded")
        seen = set()
        for row in members:
            name, path = row.filename, PurePosixPath(row.filename)
            kind = stat.S_IFMT(row.external_attr >> 16)
            if (path.is_absolute() or str(path) != name or "\\" in name or ":" in name
                    or any(part.startswith(".") or part.endswith((".", " ")) for part in path.parts)
                    or any(part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]} for part in path.parts)
                    or kind not in {0, stat.S_IFREG} or name.casefold() in seen
                    or path.suffix.lower() not in {".md", ".json", ".jsonl", ".csv", ".png", ".jpg", ".jpeg"}
                    or row.file_size > 25 * 1024 * 1024 or row.flag_bits & 1):
                raise ValueError("The authoring bundle contains an unsupported file or unsafe path")
            seen.add(name.casefold())
        if "benchmark-build-spec.json" not in archive.namelist():
            raise ValueError("Choose an authoring ZIP with benchmark-build-spec.json at its root")
        for row in members:
            target = destination / row.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(row))


class LocalLauncher:
    def __init__(self, root: Path, ui: Path):
        self.root, self.ui = root.resolve(), ui.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not (self.ui / "index.html").is_file():
            raise ValueError("The runner download is incomplete: its browser interface is missing")
        self.lock = threading.RLock()
        self.worker = None
        self.workspaces: dict[str, ResultsWorkspace] = {}

    def saved_chat_url(self) -> str | None:
        from arisekit.runtime.conversation_runner import validate_chat_url
        path = self.root / "chat-url.txt"
        return validate_chat_url(path.read_text().strip()) if path.exists() else None

    def save_chat_url(self, url: str) -> None:
        from arisekit.runtime.conversation_runner import validate_chat_url
        value = validate_chat_url(url)
        with self.lock, tempfile.NamedTemporaryFile(mode="w", dir=self.root, delete=False) as handle:
            try:
                handle.write(value + "\n")
                handle.close()
                os.replace(handle.name, self.root / "chat-url.txt")
            finally:
                Path(handle.name).unlink(missing_ok=True)

    def configure_credentials(self, credentials: dict[str, str]) -> None:
        if not isinstance(credentials, dict) or any(key not in CREDENTIALS or not isinstance(value, str) or len(value) > 8192 for key, value in credentials.items()):
            raise ValueError("Unsupported provider connection settings")
        with self.lock:
            if any(workspace.active is not None for workspace in self.workspaces.values()):
                raise ValueError("Wait for running evaluations before changing provider settings")
            for key, value in credentials.items():
                if value.strip():
                    os.environ[key] = value.strip()

    def save_bundle(self, data: bytes, name: str) -> dict:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise ValueError("Name this benchmark version using 1–120 characters")
        with self.lock, tempfile.TemporaryDirectory(dir=self.root, prefix=".import-") as temporary:
            authoring = Path(temporary) / "authoring"
            authoring.mkdir()
            extract_authoring(data, authoring)
            spec_path = authoring / "benchmark-build-spec.json"
            spec = BenchmarkScaffoldSpec.from_json(spec_path)
            if spec.data_governance.classification not in {"public", "synthetic"} or spec.data_governance.release_posture != "public":
                raise ValueError("The browser runner supports public or synthetic data with public release posture")
            scaffold_benchmark(spec, output_root=Path(temporary) / "benchmarks")
            digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
            project = self.root / digest
            if project.is_symlink():
                raise ValueError("The saved benchmark directory must not be a link")
            if project.exists():
                retained_files = {p.relative_to(project / "authoring") for p in (project / "authoring").rglob("*") if p.is_file()}
                incoming_files = {p.relative_to(authoring) for p in authoring.rglob("*") if p.is_file()}
                if retained_files != incoming_files:
                    raise ValueError("The saved project differs from this authoring bundle")
                for relative in incoming_files:
                    retained = project / "authoring" / relative
                    if retained.is_symlink() or retained.read_bytes() != (authoring / relative).read_bytes():
                        raise ValueError("The saved project differs from this authoring bundle")
            else:
                # Commit only a fully verified package and its immutable source version.
                ResultsWorkspace(Path(temporary) / "benchmarks" / spec.benchmark.slug, authoring, Path(temporary) / "results")
                metadata = {"id": digest, "name": name.strip(), "saved_at": datetime.now(timezone.utc).isoformat()}
                (Path(temporary) / "saved-version.json").write_text(json.dumps(metadata), encoding="utf-8")
                (Path(temporary) / "authoring.zip").write_bytes(data)
                os.rename(temporary, project)
            self.workspace(digest)
            return self.version(digest)

    def project(self, identifier: str) -> Path:
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise ValueError("Select a saved benchmark version")
        project = self.root / identifier
        if project.is_symlink() or not project.is_dir():
            raise ValueError("Saved benchmark version not found")
        return project

    def workspace(self, identifier: str) -> ResultsWorkspace:
        with self.lock:
            project = self.project(identifier)
            source = project / "authoring" / "benchmark-build-spec.json"
            if (project / "authoring").is_symlink() or source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != identifier:
                raise ValueError("Saved benchmark version does not match its plan")
            if identifier not in self.workspaces:
                spec = BenchmarkScaffoldSpec.from_json(source)
                self.workspaces[identifier] = ResultsWorkspace(project / "benchmarks" / spec.benchmark.slug, project / "authoring", project / "results")
            return self.workspaces[identifier]

    def version(self, identifier: str) -> dict:
        project = self.project(identifier)
        path = project / "saved-version.json"
        if path.is_symlink():
            raise ValueError("Invalid saved version metadata")
        if path.exists():
            metadata = json.loads(path.read_text())
            if metadata.get("id") != identifier or not isinstance(metadata.get("name"), str):
                raise ValueError("Invalid saved version metadata")
            return {key: metadata[key] for key in ("id", "name", "saved_at")}
        spec = BenchmarkScaffoldSpec.from_json(project / "authoring" / "benchmark-build-spec.json")
        return {"id": identifier, "name": spec.benchmark.name, "saved_at": datetime.fromtimestamp(project.stat().st_mtime, timezone.utc).isoformat()}

    def saved_versions(self) -> list[dict]:
        with self.lock:
            return sorted([self.version(p.name) for p in self.root.iterdir() if re.fullmatch(r"[a-f0-9]{64}", p.name) and p.is_dir() and not p.is_symlink()], key=lambda row: row["saved_at"], reverse=True)

    def archive(self, identifier: str) -> bytes:
        workspace = self.workspace(identifier)
        workspace._load()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(workspace.authoring.rglob("*")):
                if path.is_symlink():
                    raise ValueError("A saved authoring file must not be a link")
                if path.is_file():
                    archive.write(path, path.relative_to(workspace.authoring))
        data = stream.getvalue()
        with tempfile.TemporaryDirectory() as temporary:
            extract_authoring(data, Path(temporary))
        return data

    def open_bundle(self, data: bytes, credentials: dict[str, str]) -> str:
        with self.lock:
            if self.worker is not None:
                raise ValueError("A benchmark is already open. Restart the runner to select another bundle")
            self.configure_credentials(credentials)
            saved = self.save_bundle(data, "Imported benchmark")
            self.worker, url = make_server(self.workspace(saved["id"]), self.ui, port=0)
            threading.Thread(target=self.worker.serve_forever, daemon=True).start()
            return url

    def close(self):
        if self.worker:
            self.worker.shutdown()
            self.worker.server_close()


def make_launcher_server(launcher: LocalLauncher, port: int = 0, *, chat_url: str | None = None):
    from arisekit.runtime.conversation_runner import make_conversation_server
    return make_conversation_server(launcher, port, chat_url=chat_url or launcher.saved_chat_url(), setup_html=SETUP_HTML)




def main():
    import argparse
    import webbrowser

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui", type=Path, default=Path(__file__).with_name("workspace_ui"))
    parser.add_argument("--data", type=Path, default=Path.home() / ".arisekit" / "local-runner")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--chat-url", help="Authoring chat allowed to connect to this runner; defaults to the saved selection")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARISEKIT_RUNNER_PORT", "0")), help="Local setup port; defaults to an available port")
    args = parser.parse_args()
    launcher = LocalLauncher(args.data, args.ui)
    server, url = make_launcher_server(launcher, port=args.port, chat_url=args.chat_url)
    if not args.no_browser:
        webbrowser.open(url)
    print(f"ARISEKit local runner: {url}\nKeep this window open. Close it to stop the runner.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        launcher.close()
        server.server_close()


if __name__ == "__main__":
    main()

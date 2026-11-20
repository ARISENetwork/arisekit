"""Run the pinned HAPI WAR in a fresh JVM inside a hosted worker container."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError

from arisekit.env.docker_fhir import DockerFHIRServer, FHIR_VERSION, HAPI_IMAGE


class ProcessFHIRServer(DockerFHIRServer):
    def __init__(self, *, startup_timeout=240):
        super().__init__(startup_timeout=startup_timeout)
        self.process = None
        self.directory = None

    def start(self):
        if self.started:
            raise RuntimeError("FHIR server already started")
        war = Path(os.environ.get("ARISEKIT_HAPI_WAR", "/app/main.war"))
        expected = Path(os.environ.get("ARISEKIT_HAPI_SHA256", "/app/hapi.sha256")).read_text().strip()
        actual = hashlib.sha256(war.read_bytes()).hexdigest()
        if actual != expected or len(expected) != 64:
            raise ValueError("Hosted HAPI WAR differs from the build-time pinned artifact")
        self.image_id = "war-sha256:" + actual
        self.runtime_identity = {"kind": "fresh-jvm", "hapi_source_image": HAPI_IMAGE,
            "war_sha256": actual, "worker_image": os.environ.get("ARISEKIT_WORKER_IMAGE", "local-build")}
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}/fhir"
        self.directory = tempfile.TemporaryDirectory(prefix="arisekit-hapi-")
        Path(self.directory.name, "main.war").symlink_to(war)
        self.logs = tempfile.TemporaryFile()
        command = ["java", "-Xms256m", "-Xmx1024m", "--class-path", str(war),
            "-Dloader.path=main.war!/WEB-INF/classes/,main.war!/WEB-INF/,/app/extra-classes",
            "org.springframework.boot.loader.PropertiesLauncher", f"--server.port={port}",
            "--server.address=127.0.0.1", "--hapi.fhir.fhir_version=R4",
            "--spring.datasource.url=jdbc:h2:mem:arisekit;DB_CLOSE_DELAY=-1"]
        try:
            self.process = subprocess.Popen(command, cwd=self.directory.name, stdout=self.logs,
                stderr=subprocess.STDOUT, start_new_session=True)
            self.started = True
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    break
                try:
                    self.metadata = self.request("GET", "metadata", timeout=3)
                    if self.metadata.get("fhirVersion") != FHIR_VERSION:
                        raise ValueError("Hosted HAPI must report FHIR R4 4.0.1")
                    return self
                except (OSError, HTTPError):
                    time.sleep(0.5)
            self.logs.seek(0)
            raise RuntimeError("Hosted HAPI readiness failed: " + self.logs.read().decode(errors="replace")[-3000:])
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        if self.directory is not None:
            self.directory.cleanup()
        if hasattr(self, "logs"):
            self.logs.close()
        self.started = False



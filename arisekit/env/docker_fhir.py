"""Disposable, digest-pinned HAPI R4 servers and policy-limited HTTP tools."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from typing import Any

from arisekit.types import Tool

HAPI_IMAGE = "hapiproject/hapi@sha256:34c86fd5805df77c2b9d9c10538050b16ac3dc244352da0ebe4717f931330775"
HAPI_RELEASE = "v8.8.0-1"
FHIR_VERSION = "4.0.1"
CATALOG = "arisekit.fhir-http-tools.v1"
ACTIONS = ("read", "search", "create", "update", "delete")
ID = re.compile(r"^[A-Za-z0-9.-]{1,64}$")
RESOURCE = re.compile(r"^[A-Z][A-Za-z]{1,63}$")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stable_resource(value: dict) -> dict:
    result = copy.deepcopy(value)
    meta = result.get("meta", {})
    for key in ("versionId", "lastUpdated"):
        meta.pop(key, None)
    if not meta:
        result.pop("meta", None)
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("FHIR redirects are not allowed")


class DockerFHIRServer:
    """Own a single empty R4 server, bound only to an ephemeral loopback port."""

    def __init__(self, *, startup_timeout: float = 180):
        self.name = "arisekit-fhir-" + uuid.uuid4().hex
        self.startup_timeout = startup_timeout
        self.base_url = ""
        self.image_id = ""
        self.started = False
        self.opener = build_opener(_NoRedirect)

    @staticmethod
    def docker(*args: str, check=True, timeout=30) -> str:
        try:
            result = subprocess.run(["docker", *args], capture_output=True, text=True,
                                    check=check, timeout=timeout)
            return result.stdout.strip()
        except FileNotFoundError as exc:
            raise RuntimeError("Docker executable is missing; install and start Docker Desktop") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("Docker command failed: " + exc.stderr.strip()[-2000:]) from exc

    def start(self):
        if self.started:
            raise RuntimeError("FHIR server already started")
        # Pull is explicit so evaluation cannot silently change or download an image.
        self.image_id = self.docker("image", "inspect", HAPI_IMAGE, "--format", "{{.Id}}")
        try:
            self.docker("run", "--detach", "--rm", "--name", self.name,
                        "--label", "org.arisekit.environment=fhir-r4", "--cpus", "2", "--memory", "2g",
                        "--publish", "127.0.0.1::8080", "--env", "hapi.fhir.fhir_version=R4",
                        "--env", "spring.datasource.url=jdbc:h2:mem:arisekit;DB_CLOSE_DELAY=-1",
                        "--env", "JAVA_TOOL_OPTIONS=-Xms256m -Xmx1024m", self.image_id, timeout=60)
            self.started = True
            port = self.docker("port", self.name, "8080/tcp").rsplit(":", 1)[1]
            self.base_url = f"http://127.0.0.1:{int(port)}/fhir"
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                try:
                    metadata = self.request("GET", "metadata", timeout=3)
                    if metadata.get("fhirVersion") != FHIR_VERSION:
                        raise ValueError("FHIR server must report R4 4.0.1")
                    if self.docker("inspect", self.name, "--format", "{{.Image}}") != self.image_id:
                        raise ValueError("running FHIR image differs from pinned image")
                    self.metadata = metadata
                    return self
                except (OSError, HTTPError):
                    time.sleep(0.5)
            logs = self.docker("logs", "--tail", "15", self.name, check=False)
            raise RuntimeError(f"FHIR R4 readiness timed out after {self.startup_timeout}s: {logs[-2000:]}")
        except BaseException:
            self.stop()
            raise

    def request(self, method: str, path: str, body=None, *, timeout=15):
        url = path if path.startswith("http") else self.base_url + "/" + path
        parsed, base = urlparse(url), urlparse(self.base_url)
        if (parsed.netloc != base.netloc or parsed.scheme != base.scheme
                or not (parsed.path == base.path or parsed.path.startswith(base.path + "/"))):
            raise ValueError("FHIR pagination must stay on the same server")
        data = canonical(body).encode() if body is not None else None
        request = Request(url, data=data, method=method, headers={
            "Accept": "application/fhir+json", "Content-Type": "application/fhir+json",
            "Prefer": "handling=strict", "Cache-Control": "no-cache",
        })
        try:
            with self.opener.open(request, timeout=timeout) as response:
                payload = response.read(16 * 1024 * 1024 + 1)
                if len(payload) > 16 * 1024 * 1024:
                    raise ValueError("FHIR response exceeds 16 MiB")
                return json.loads(payload) if payload else None
        except HTTPError as exc:
            if exc.code in (404, 410) and method == "GET":
                return None
            detail = exc.read(4000).decode(errors="replace")
            raise RuntimeError(f"FHIR {method} failed ({exc.code}): {detail}") from exc

    def resources(self, resource_type: str, params=None) -> list[dict]:
        query = {"_count": "200", **(params or {})}
        url = self.base_url + "/" + resource_type + "?" + urlencode(query, doseq=True)
        seen, resources = set(), []
        while url:
            if url in seen or len(seen) >= 50:
                raise ValueError("FHIR pagination loop or page limit")
            seen.add(url)
            bundle = self.request("GET", url)
            if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
                raise ValueError("FHIR search did not return a Bundle")
            resources.extend(entry["resource"] for entry in bundle.get("entry", [])
                             if entry.get("search", {}).get("mode", "match") == "match")
            if len(resources) > 5000:
                raise ValueError("FHIR search exceeds 5000 resources")
            next_links = [link["url"] for link in bundle.get("link", []) if link.get("relation") == "next"]
            if len(next_links) > 1:
                raise ValueError("FHIR search has multiple next links")
            url = next_links[0] if next_links else None
        values = [stable_resource(r) for r in resources]
        return values if params else sorted(values, key=lambda r: (r["resourceType"], r["id"]))

    def stop(self):
        if self.started:
            self.docker("rm", "--force", self.name, check=False)
            self.started = False

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()


def validate_policy(policy: Any) -> dict:
    if not isinstance(policy, dict) or not policy:
        raise ValueError("resources must map FHIR resource types to allowed actions")
    for resource_type, actions in policy.items():
        if not RESOURCE.fullmatch(resource_type):
            raise ValueError("invalid FHIR resource type")
        if not isinstance(actions, list) or not actions or len(set(actions)) != len(actions) or set(actions) - set(ACTIONS):
            raise ValueError("resource actions must be a distinct nonempty subset of read/search/create/update/delete")
    return copy.deepcopy(policy)


def validate_seed(bundle: Any, policy: dict) -> str:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle" or bundle.get("type") != "collection":
        raise ValueError("seed must be a collection Bundle")
    resources = [entry["resource"] for entry in bundle.get("entry", [])]
    if not 1 <= len(resources) <= 1000:
        raise ValueError("seed must contain 1 to 1000 resources")
    identities = set()
    for resource in resources:
        rt, rid = resource.get("resourceType"), resource.get("id")
        if rt not in policy or not isinstance(rid, str) or not ID.fullmatch(rid):
            raise ValueError("seed resource needs an authorized type and FHIR id")
        if (rt, rid) in identities:
            raise ValueError("duplicate seed identity")
        identities.add((rt, rid))
    patients = [r["id"] for r in resources if r["resourceType"] == "Patient"]
    if len(patients) != 1:
        raise ValueError("each attempt must contain exactly one Patient")
    patient = patients[0]
    for resource in resources:
        _patient_scope(resource, patient)
        for reference in _references(resource):
            if reference not in {f"{rt}/{rid}" for rt, rid in identities}:
                raise ValueError("seed references must resolve inside the seed Bundle")
    return patient


def _references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "reference":
                yield child
            else:
                yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def _patient_scope(resource, patient):
    if resource["resourceType"] == "Patient":
        if resource.get("id") != patient:
            raise PermissionError("resource belongs to another patient")
    elif not any(resource.get(field, {}).get("reference") == f"Patient/{patient}" for field in ("subject", "patient", "for")):
        raise PermissionError("resource must reference the attempt patient")
    for reference in _references(resource):
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Z][A-Za-z]+/[A-Za-z0-9.-]{1,64}", reference):
            raise PermissionError("only relative FHIR references are allowed")
        if reference.startswith("Patient/") and reference != f"Patient/{patient}":
            raise PermissionError("reference targets another patient")


class HTTPFHIREnvironment:
    """Enforce the frozen resource/action policy before every agent request."""

    def __init__(self, server: DockerFHIRServer, bundle: dict, policy: dict):
        self.server, self.policy = server, validate_policy(policy)
        self.bundle = copy.deepcopy(bundle)
        self.patient = validate_seed(bundle, self.policy)
        self.counter = 0

    def seed(self, resources=None):
        resources = resources if resources is not None else [entry["resource"] for entry in self.bundle["entry"]]
        # A transaction resolves references even when entries arrive out of order.
        self.server.request("POST", "", {"resourceType": "Bundle", "type": "transaction", "entry": [
            {"resource": r, "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"}} for r in resources
        ]})

    def snapshot(self):
        resources = []
        for rt in sorted(self.policy):
            resources.extend(self.server.resources(rt))
        return resources

    def _authorize(self, rt, action):
        if action not in self.policy.get(rt, []):
            raise PermissionError(f"{action} {rt} is outside the frozen resource policy")

    def read(self, resource_type: str, id: str):
        self._authorize(resource_type, "read")
        if not isinstance(id, str) or not ID.fullmatch(id):
            raise ValueError("invalid resource id")
        result = self.server.request("GET", f"{resource_type}/{id}")
        if result:
            _patient_scope(result, self.patient)
        return stable_resource(result) if result else None

    def search(self, resource_type: str, params: dict):
        self._authorize(resource_type, "search")
        capabilities = next((r for r in self.server.metadata["rest"][0]["resource"] if r["type"] == resource_type), {})
        allowed = {p["name"] for p in capabilities.get("searchParam", [])} | {"_id", "_sort", "_count"}
        if not isinstance(params, dict) or any(k not in allowed or k.startswith("_") and k not in {"_id", "_sort", "_count"} for k in params):
            raise ValueError("unsupported FHIR search parameter")
        params = copy.deepcopy(params)
        if "_count" in params and type(params["_count"]) is int:
            params["_count"] = str(params["_count"])
        if any(not isinstance(v, str) or not v for v in params.values()):
            raise ValueError("search values must be nonempty strings; _count may also be an integer")
        if "_count" in params and (not params["_count"].isdigit() or not 1 <= int(params["_count"]) <= 5000):
            raise ValueError("_count must be from 1 through 5000")
        results = self.server.resources(resource_type, params)
        for r in results:
            _patient_scope(r, self.patient)
        return results

    def _write(self, resource, action):
        resource = copy.deepcopy(resource)
        rt = resource.get("resourceType")
        self._authorize(rt, action)
        _patient_scope(resource, self.patient)
        for reference in _references(resource):
            target_type, target_id = reference.split("/")
            if target_type not in self.policy or not self.server.request("GET", reference):
                raise PermissionError("write reference must resolve in the authorized chart")
        if action == "create":
            if "id" in resource:
                raise ValueError("create resources must omit id")
            self.counter += 1
            resource["id"] = "arise-" + digest([self.patient, self.counter])[:24]
        rid = resource.get("id")
        if not isinstance(rid, str) or not ID.fullmatch(rid):
            raise ValueError("update requires a valid resource id")
        existing = self.server.request("GET", f"{rt}/{rid}")
        if action == "update" and not existing:
            raise ValueError("update target does not exist")
        if existing:
            _patient_scope(existing, self.patient)
        if action == "create" and existing:
            raise ValueError("allocated create id collides with an existing resource")
        return stable_resource(self.server.request("PUT", f"{rt}/{rid}", resource))

    def create(self, resource: dict):
        return self._write(resource, "create")

    def update(self, resource: dict):
        return self._write(resource, "update")

    def delete(self, resource_type: str, id: str):
        self._authorize(resource_type, "delete")
        if not isinstance(id, str) or not ID.fullmatch(id):
            raise ValueError("invalid resource id")
        existing = self.server.request("GET", f"{resource_type}/{id}")
        if existing:
            _patient_scope(existing, self.patient)
            self.server.request("DELETE", f"{resource_type}/{id}")
        return {"deleted": f"{resource_type}/{id}"}

    def tools(self):
        resource_type = {"type": "string", "enum": sorted(self.policy)}
        definitions = [
            ("read", self.read, {"resource_type": resource_type, "id": {"type": "string"}}),
            ("search", self.search, {"resource_type": resource_type, "params": {"type": "object", "additionalProperties": {"anyOf": [{"type": "string"}, {"type": "integer"}]}}}),
            ("create", self.create, {"resource": {"type": "object"}}),
            ("update", self.update, {"resource": {"type": "object"}}),
            ("delete", self.delete, {"resource_type": resource_type, "id": {"type": "string"}}),
        ]
        return [Tool(name="fhir_" + action, description=f"FHIR R4 {action}; obey resource policy {canonical(self.policy)}",
                     parameters={"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}, fn=fn)
                for action, fn, fields in definitions if any(action in actions for actions in self.policy.values())]

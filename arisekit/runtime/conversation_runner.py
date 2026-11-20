"""Authenticated connection between the authoring chat and a local runner."""

import base64
import html
import json
import secrets
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_ARCHIVE = 64 * 1024 * 1024


def validate_chat_url(chat_url):
    if not isinstance(chat_url, str) or any(ord(char) < 33 for char in chat_url):
        raise ValueError("Use an HTTPS authoring URL or a local development URL")
    target = urlsplit(chat_url)
    target.port
    if (target.username or target.password or target.fragment or target.query
            or not target.hostname or target.scheme not in {"https", "http"}
            or (target.scheme == "http" and target.hostname not in {"127.0.0.1", "localhost"})):
        raise ValueError("Use an HTTPS authoring URL or a local development URL")
    return chat_url


def make_conversation_server(launcher, port, *, chat_url, setup_html):
    target = urlsplit(validate_chat_url(chat_url)) if chat_url else None
    chat_origin = f"{target.scheme}://{target.netloc}" if target else None
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def local_origin(self):
            return f"http://127.0.0.1:{self.server.server_port}"

        def allowed_origin(self):
            return self.headers.get("Origin", self.local_origin()) in {self.local_origin(), chat_origin}

        def valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def authorized(self):
            return (self.valid_host() and self.allowed_origin()
                    and secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"))

        def reply(self, code, value, content_type="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Vary", "Origin")
            if chat_origin and self.valid_host() and self.headers.get("Origin") == chat_origin:
                self.send_header("Access-Control-Allow-Origin", chat_origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.reply(204 if self.valid_host() and self.allowed_origin() else 403, b"")

        def selection(self):
            parts = urlsplit(self.path).path.split("/")
            if len(parts) < 4 or parts[1:3] != ["api", "benchmarks"]:
                raise ValueError("Unknown runner resource")
            identifier = parts[3]
            launcher.project(identifier)
            return identifier, "/".join(parts[4:])

        def do_GET(self):
            route = urlsplit(self.path).path
            if route == "/" and self.valid_host():
                from arisekit import __version__
                page = setup_html.replace("__VERSION__", __version__).replace("__CHAT_URL__", html.escape(chat_url or "", quote=True))
                return self.reply(200, page.encode(), "text/html; charset=utf-8")
            if not self.authorized():
                return self.reply(403, {"error": "Reconnect using the local runner's launch link"})
            try:
                if route == "/api/benchmarks":
                    return self.reply(200, launcher.saved_versions())
                identifier, resource = self.selection()
                workspace = launcher.workspace(identifier)
                if resource == "bundle":
                    return self.reply(200, launcher.archive(identifier), "application/zip")
                if resource == "workspace/jobs":
                    return self.reply(200, list(workspace.jobs.values()))
                if workspace.active is not None:
                    return self.reply(409, {"error": "An operation is running"})
                if resource == "workspace":
                    return self.reply(200, workspace.snapshot())
                if resource == "workspace/export":
                    from arisekit.workspace_bundle import export_bundle
                    return self.reply(200, export_bundle(workspace))
                return self.reply(404, {"error": "Unknown runner resource"})
            except (ValueError, TypeError, KeyError, OSError) as exc:
                self.reply(422, {"error": str(exc)})

        def do_POST(self):
            nonlocal chat_url, chat_origin
            if not self.authorized():
                return self.reply(403, {"error": "Reconnect using the local runner's launch link"})
            try:
                route = urlsplit(self.path).path
                maximum = MAX_ARCHIVE * 4 // 3 + 65536 if route in {"/open", "/api/benchmarks"} else 65536
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Content-Type") != "application/json" or not 0 < length <= maximum:
                    raise ValueError("Unsupported runner request size or format")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected an operation object")
                if route == "/chat":
                    if self.headers.get("Origin", self.local_origin()) != self.local_origin():
                        return self.reply(403, {"error": "Choose the authoring chat on the local setup page"})
                    if set(payload) != {"url"}:
                        raise ValueError("Expected an authoring chat URL")
                    updated = validate_chat_url(payload["url"])
                    launcher.save_chat_url(updated)
                    chat_url = updated
                    target = urlsplit(updated)
                    chat_origin = f"{target.scheme}://{target.netloc}"
                    return self.reply(200, {"url": updated})
                if route == "/connection":
                    # Provider credentials are configured only on the local setup page.
                    if self.headers.get("Origin", self.local_origin()) != self.local_origin():
                        return self.reply(403, {"error": "Set provider credentials in the local runner"})
                    if set(payload) != {"credentials"}:
                        raise ValueError("Expected provider connection settings")
                    launcher.configure_credentials(payload["credentials"])
                    return self.reply(200, {"connected": True})
                if route == "/open":
                    if self.headers.get("Origin", self.local_origin()) != self.local_origin():
                        return self.reply(403, {"error": "Use the local setup page to import a bundle"})
                    if set(payload) != {"archive", "credentials"}:
                        raise ValueError("Choose an authoring ZIP")
                    return self.reply(200, {"url": launcher.open_bundle(base64.b64decode(payload["archive"], validate=True), payload["credentials"])})
                if route == "/api/benchmarks":
                    if set(payload) != {"archive", "name"}:
                        raise ValueError("Expected a named benchmark version")
                    return self.reply(201, launcher.save_bundle(base64.b64decode(payload["archive"], validate=True), payload["name"]))
                identifier, resource = self.selection()
                if not resource.startswith("workspace/"):
                    raise ValueError("Unknown runner operation")
                with launcher.lock:
                    job = launcher.workspace(identifier).submit(resource.removeprefix("workspace/"), payload)
                self.reply(202, {"id": job})
            except (ValueError, TypeError, KeyError, OSError, zipfile.BadZipFile) as exc:
                self.reply(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server, f"http://127.0.0.1:{server.server_port}/#token={token}"

"""Loopback-only authenticated JSON API. The browser talks to HA, never to this API."""
from __future__ import annotations
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import socket
from . import addon_repos
from .common import AppError, atomic, read_token
from .hostctl import Host, OPERATIONS, dispatch

MAX_BODY = 128 * 1024


def make_server(manager, port: int | None = None):
    token = read_token(manager.config)
    host = Host(manager.config)

    class Handler(BaseHTTPRequestHandler):
        server_version = "OPIHA-Native/1"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_):
            # Never log request bodies, bearer tokens, private app logs or raw paths.
            return

        def reply(self, status: int, payload: dict):
            body = json.dumps(payload, ensure_ascii=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def authenticated(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            if self.headers.get("Origin") or self.headers.get("Transfer-Encoding"):
                self.reply(403, {"error": "Browser origins and transfer-encoded requests are not accepted"})
                return False
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
                self.reply(401, {"error": "Authentication required"})
                return False
            return True

        def do_OPTIONS(self):
            self.reply(405, {"error": "No browser CORS endpoint"})

        def do_GET(self):
            if not self.authenticated():
                return
            try:
                if self.path == "/v1/overview":
                    value = manager.overview()
                elif self.path == "/v1/metrics":
                    value = manager.overview(include_stats=True)
                elif match := re.fullmatch(r"/v1/jobs/([A-Za-z0-9_-]{1,80})", self.path):
                    value = manager.job(match[1])
                elif match := re.fullmatch(r"/v1/apps/([a-z0-9_-]{1,32})/(logs|ingress)", self.path):
                    value = getattr(manager, match[2])(match[1])
                elif self.path == "/v1/repos":
                    value = {"repositories": manager.repos.list(), "suggested": addon_repos.SUGGESTED,
                             "ha_token_configured": (manager.root / "ha-token").is_file()}
                elif match := re.fullmatch(r"/v1/repos/([0-9a-f]{8})/addons", self.path):
                    value = {"repository": match[1], "addons": manager.repos.addons(match[1])}
                else:
                    self.reply(404, {"error": "No such API route"})
                    return
                self.reply(200, value)
            except AppError as exc:
                self.reply(409, {"error": str(exc)})
            except Exception:
                self.reply(503, {"error": "Native manager could not complete the read"})

        def do_POST(self):
            if not self.authenticated():
                return
            try:
                if self.headers.get_content_type() != "application/json":
                    self.reply(415, {"error": "JSON content is required"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    self.reply(413, {"error": "Invalid request size"})
                    return
                document = json.loads(self.rfile.read(length))
                if not isinstance(document, dict):
                    raise AppError("Request must be a JSON object")
                if self.path == "/v1/plan":
                    if set(document) - {"app", "action", "options"}:
                        raise AppError("Unknown planning fields")
                    value = manager.plan(document["app"], document["action"], document.get("options"))
                elif self.path == "/v1/repos/add":
                    if set(document) != {"url"}:
                        raise AppError("Send only the repository URL")
                    value = manager.repos.add(document["url"])
                elif self.path in {"/v1/repos/refresh", "/v1/repos/remove"}:
                    if set(document) != {"id"} or not isinstance(document["id"], str):
                        raise AppError("Send only the repository id")
                    if self.path.endswith("remove"):
                        manager.repos.remove(document["id"])
                        value = {"removed": document["id"]}
                    else:
                        value = manager.repos.refresh(document["id"])
                elif self.path == "/v1/addon/plan":
                    if set(document) - {"repository", "folder", "options"} or not {"repository", "folder"} <= set(document):
                        raise AppError("Unknown add-on planning fields")
                    value = manager.plan_addon(document["repository"], document["folder"], document.get("options"))
                elif self.path == "/v1/addons/ha-token":
                    if set(document) != {"token"} or not isinstance(document["token"], str) or not re.fullmatch(r"[A-Za-z0-9._-]{20,4096}", document["token"]):
                        raise AppError("Send a Home Assistant long-lived access token")
                    atomic(manager.root / "ha-token", (document["token"] + "\n").encode())
                    value = {"ha_token_configured": True}
                elif self.path == "/v1/apply":
                    if set(document) != {"id", "confirm"} or not isinstance(document["id"], str):
                        raise AppError("Invalid plan approval")
                    value = manager.submit(document["id"], document["confirm"])
                elif match := re.fullmatch(r"/v1/host/([a-z_]{1,32})", self.path):
                    if match[1] not in OPERATIONS:
                        self.reply(404, {"error": "No such API route"})
                        return
                    value = dispatch(host, match[1], document)
                elif self.path == "/v1/apps/mosquitto/credentials":
                    if document != {"confirm": True}:
                        raise AppError("Confirm before revealing a private generated credential")
                    value = manager.credentials("mosquitto")
                else:
                    self.reply(404, {"error": "No such API route"})
                    return
                self.reply(200, value)
            except (AppError, ValueError, KeyError, TypeError) as exc:
                self.reply(400, {"error": str(exc) if isinstance(exc, AppError) else "Invalid JSON request"})
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                return
            except Exception:
                self.reply(503, {"error": "Native manager could not complete the request"})

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 16

        def server_close(self):
            host.close()
            super().server_close()

    return Server(("127.0.0.1", manager.config["port"] if port is None else port), Handler)

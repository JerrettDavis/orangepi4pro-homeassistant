"""Loopback-only authenticated JSON API. The browser talks to HA, never to this API."""
from __future__ import annotations
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import socket
from .common import AppError, read_token

MAX_BODY = 128 * 1024


def make_server(manager, port: int | None = None):
    token = read_token(manager.config)

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
                elif self.path == "/v1/apply":
                    if set(document) != {"id", "confirm"} or not isinstance(document["id"], str):
                        raise AppError("Invalid plan approval")
                    value = manager.submit(document["id"], document["confirm"])
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
        request_queue_size = 8

    return Server(("127.0.0.1", manager.config["port"] if port is None else port), Handler)

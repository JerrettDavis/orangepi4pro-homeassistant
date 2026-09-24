from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import urllib.parse
from .common import REPO
from .status import snapshot


def make_server(cfg: dict, host: str = "127.0.0.1", port: int = 8099) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("The diagnostic service is loopback-only")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return  # No client URLs in logs.
        def do_GET(self):
            route = urllib.parse.urlsplit(self.path).path
            if route == "/health.json":
                body = json.dumps(snapshot(cfg)).encode()
                content = "application/json"
            elif route == "/ui.json":
                body = json.dumps({"ha_url": cfg["ha_url"], "dashboard_path": cfg["dashboard_path"]}).encode()
                content = "application/json"
            elif route == "/":
                body = (REPO / "web/index.html").read_bytes()
                content = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)
    return ThreadingHTTPServer((host, port), Handler)

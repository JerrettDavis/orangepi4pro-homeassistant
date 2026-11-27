import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import zipfile

import pytest

from opiha import oidc, vendor
from opiha.common import ApplianceError, atomic_json, sha256


def test_pinned_release_seeds_without_overwriting(tmp_path):
    assert vendor.seed_oidc(tmp_path)
    target = tmp_path / "custom_components" / "auth_oidc"
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["domain"] == "auth_oidc" and manifest["version"] == "1.3.0"
    marker = target / "__init__.py"
    marker.write_text("existing version")
    assert not vendor.seed_oidc(tmp_path)
    assert marker.read_text() == "existing version"


def test_oidc_archive_rejects_bad_checksum_and_zip_traversal(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "vendor").mkdir(parents=True)
    archive = root / "vendor" / "auth-oidc.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape", "bad")
        z.writestr("manifest.json", '{"domain":"auth_oidc","version":"1.3.0"}')
    lock = root / "vendor" / "auth-oidc.lock.json"
    atomic_json(lock, {"version": "1.3.0", "sha256": "bad"})
    monkeypatch.setattr(vendor, "REPO", root)
    with pytest.raises(ApplianceError, match="checksum"):
        vendor.seed_oidc(tmp_path / "ha")
    atomic_json(lock, {"version": "1.3.0", "sha256": sha256(archive)})
    with pytest.raises(ApplianceError):
        vendor.seed_oidc(tmp_path / "ha")
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / "ha" / "custom_components" / "auth_oidc").exists()


def test_configure_uses_safe_ui_flow_without_user_linking(tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o600)
    calls = []
    steps = ["discovery_url", "validate_connection", "client_config",
             "groups_config", "user_linking"]

    def request(opener, base, token, method, path, body=None):
        calls.append((method, path, body))
        assert token == "fixture-token"
        if method == "GET":
            return []
        if path.endswith("/flow"):
            return {"type": "form", "flow_id": "ABC123", "step_id": "user"}
        step = len([c for c in calls if c[1].endswith("/ABC123")])
        return ({"type": "form", "step_id": steps[step - 1], "errors": {}}
                if step <= len(steps) else {"type": "create_entry"})

    monkeypatch.setattr(oidc, "_request", request)
    assert oidc.configure(token_file)["configured"]
    assert calls[-2][2] == {"enable_groups": False}
    assert calls[-1][2] == {"enable_user_linking": False, "require_existing_user": True}
    assert not any(c[0] == "DELETE" for c in calls)


def test_configure_preserves_existing_entry(tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o600)
    calls = []

    def request(opener, base, token, method, path, body=None):
        calls.append(method)
        return [{"domain": "auth_oidc"}]

    monkeypatch.setattr(oidc, "_request", request)
    assert oidc.configure(token_file) == {"configured": False, "reason": "existing_entry_preserved"}
    assert calls == ["GET"]


def test_failed_flow_is_removed(tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o600)
    calls = []

    def request(opener, base, token, method, path, body=None):
        calls.append(method)
        if method == "GET":
            return []
        if method == "DELETE":
            return None
        if path.endswith("/flow"):
            return {"type": "form", "flow_id": "ABC123", "step_id": "user"}
        return {"type": "form", "step_id": "discovery_url", "errors": {"base": "invalid"}}

    monkeypatch.setattr(oidc, "_request", request)
    with pytest.raises(ApplianceError, match="OIDC setup stopped"):
        oidc.configure(token_file)
    assert calls[-1] == "DELETE"


def test_unexpected_flow_response_is_cleaned_up(tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o600)
    calls = []

    def request(opener, base, token, method, path, body=None):
        calls.append(method)
        if method == "GET":
            return []
        if path.endswith("/flow") and method == "POST":
            return {"type": "form", "flow_id": "ABC123", "step_id": "user"}
        return None

    monkeypatch.setattr(oidc, "_request", request)
    with pytest.raises(ApplianceError, match="OIDC setup stopped"):
        oidc.configure(token_file)
    assert calls[-1] == "DELETE"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission check")
def test_refuses_public_token_file(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o644)
    with pytest.raises(ApplianceError, match="accessible to group or others"):
        oidc.configure(token_file)


def test_refuses_sending_token_over_untrusted_http(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o600)
    with pytest.raises(ApplianceError, match="HTTPS"):
        oidc.configure(token_file, "http://example.com")


def test_configuration_flow_over_http(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o600)
    received = []
    steps = ["discovery_url", "validate_connection", "client_config",
             "groups_config", "user_linking"]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            received.append((self.command, self.path, self.headers.get("Authorization"), None))
            self.respond([])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.command, self.path, self.headers.get("Authorization"), body))
            if self.path.endswith("/flow"):
                self.respond({"type": "form", "flow_id": "ABC123", "step_id": "user"})
                return
            number = sum(path.endswith("/ABC123") for _, path, _, _ in received)
            if number <= len(steps):
                self.respond({"type": "form", "step_id": steps[number - 1], "errors": {}})
            else:
                self.respond({"type": "create_entry"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert oidc.configure(token_file, f"http://127.0.0.1:{server.server_port}")["configured"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert all(header == "Bearer fixture-token" for _, _, header, _ in received)
    assert received[-1][3] == {"enable_user_linking": False, "require_existing_user": True}


def test_configuration_does_not_follow_redirects(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("fixture-token")
    token_file.chmod(0o600)
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            paths.append(self.path)
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/redirected")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(ApplianceError, match="HTTP 302"):
            oidc.configure(token_file, f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert paths == ["/api/config/config_entries/entry"]

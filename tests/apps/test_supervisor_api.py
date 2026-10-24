from __future__ import annotations
import http.server
import json
import threading
import urllib.request
import urllib.error
import pytest
from opiha_apps import addon_runtime, catalog, supervisor_api
from opiha_apps.common import write_json
from conftest import execute, execute_addon
from test_addon_manager import MOSQ, EDITOR, make_repo, slug as slug_of, clean_registry  # noqa: F401

NODE = """name: Needs MQTT
version: '1.0'
slug: consumer
description: consumer
arch: [aarch64]
image: example/{arch}-consumer
apparmor: false
homeassistant_api: true
services: ['mqtt:want']
options: {a: 1}
schema: {a: 'int(0,5)'}
"""
PROVIDER = MOSQ.replace("hassio_api: true\n", "hassio_api: true\nservices: ['mqtt:provide']\n")


@pytest.fixture
def world(manager, tmp_path):
    manager.ha_config = str(tmp_path / "ha")
    write_json(tmp_path / "etc/appliance.json", {"mode": "appliance", "data_dir": str(tmp_path), "ha_version": "2026.9.3",
                                                  "ha_url": "http://127.0.0.1:1"})
    repo = make_repo(manager, {"mosquitto/config.yaml": PROVIDER, "consumer/config.yaml": NODE,
                               "configurator/config.yaml": EDITOR})
    execute_addon(manager, repo, "mosquitto", {"grants": ["ha_api"]})
    execute_addon(manager, repo, "consumer", {"grants": ["ha_api"]})
    shim = supervisor_api.Shim(manager)
    tokens = {n: addon_runtime.token(manager, slug_of(repo, n)) for n in ("mosquitto", "consumer")}
    return manager, shim, repo, tokens


def call(shim, method, path, token, body=None):
    status, payload, kind = shim.handle(method, path, token, b"" if body is None else json.dumps(body).encode())
    return status, payload


def test_unknown_or_malformed_tokens_are_refused(world):
    _, shim, _, tokens = world
    for token in ("", "x", "0" * 64, "../" + tokens["consumer"]):
        assert call(shim, "GET", "/addons/self/info", token)[0] == 401


def test_self_info_options_and_validation(world):
    manager, shim, repo, tokens = world
    status, info = call(shim, "GET", "/addons/self/info", tokens["consumer"])
    data = info["data"]
    assert status == 200 and data["slug"].endswith("_consumer") and data["state"] == "stopped" and data["version"] == "1.0"
    assert call(shim, "GET", "/addons/self/options/config", tokens["consumer"])[1]["data"] == {"a": 1}
    assert call(shim, "POST", "/addons/self/options", tokens["consumer"], {"options": {"a": 4}})[1]["result"] == "ok"
    s = slug_of(repo, "consumer")
    assert json.loads((manager.app_dir(s) / "data/options.json").read_text()) == {"a": 4}
    assert call(shim, "POST", "/addons/self/options", tokens["consumer"], {"options": {"a": 9}})[0] == 400
    assert call(shim, "POST", "/addons/self/options/validate", tokens["consumer"], {"options": {"a": 9}})[1]["data"]["valid"] is False


def test_an_addon_only_sees_its_own_data(world):
    _, shim, repo, tokens = world
    a = call(shim, "GET", "/addons/self/info", tokens["consumer"])[1]["data"]["slug"]
    b = call(shim, "GET", "/addons/self/info", tokens["mosquitto"])[1]["data"]["slug"]
    assert a != b
    assert call(shim, "GET", "/addons/" + b + "/info", tokens["consumer"])[0] == 404  # another add-on's info is not served


def test_mqtt_service_registry_roles(world):
    _, shim, _, tokens = world
    assert call(shim, "GET", "/services/mqtt", tokens["consumer"])[0] == 400  # nothing published yet
    assert call(shim, "POST", "/services/mqtt", tokens["consumer"], {"host": "x"})[0] == 403  # consumers cannot publish
    creds = {"host": "core-mosquitto", "port": 1883, "username": "u", "password": "p", "ssl": False, "protocol": "3.1.1"}
    assert call(shim, "POST", "/services/mqtt", tokens["mosquitto"], creds)[1]["result"] == "ok"
    got = call(shim, "GET", "/services/mqtt", tokens["consumer"])[1]["data"]
    assert got["host"] == "core-mosquitto" and "provider" not in got
    assert call(shim, "DELETE", "/services/mqtt", tokens["consumer"])[0] == 403
    assert call(shim, "DELETE", "/services/mqtt", tokens["mosquitto"])[1]["result"] == "ok"
    assert call(shim, "GET", "/services/mqtt", tokens["consumer"])[0] == 400


def test_unimplemented_paths_are_honest_and_recorded(world):
    manager, shim, _, tokens = world
    status, payload = call(shim, "GET", "/addons/self/changelog", tokens["consumer"])
    assert status == 404 and payload["result"] == "error"
    assert call(shim, "POST", "/discovery", tokens["mosquitto"], {"service": "mqtt"})[0] == 501
    assert call(shim, "GET", "/core/websocket", tokens["consumer"])[0] == 501
    recorded = json.loads((manager.root / "shim-unimplemented.json").read_text())
    assert recorded["GET /addons/self/changelog"] == 1 and "POST /discovery" in recorded


def test_core_api_proxy_needs_declaration_and_token_then_forwards_with_query(world):
    manager, shim, _, tokens = world
    assert call(shim, "GET", "/core/api/states", tokens["mosquitto"])[0] == 403  # no homeassistant_api declared
    assert call(shim, "GET", "/core/api/states", tokens["consumer"])[0] == 503  # administrator has not provided a token
    seen = {}

    class Fake(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.update(path=self.path, auth=self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'[{"entity_id": "light.a"}]')

        def log_message(self, *_):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        write_json(manager.root.parent / "etc/appliance.json", {"mode": "appliance", "data_dir": str(manager.root.parent),
                   "ha_url": f"http://127.0.0.1:{server.server_address[1]}"})
        (manager.root / "ha-token").write_text("LONG-LIVED\n")
        status, payload, ctype = shim.handle("GET", "/core/api/states?filter=x", tokens["consumer"])
        assert status == 200 and json.loads(payload) == [{"entity_id": "light.a"}]
        assert seen == {"path": "/api/states?filter=x", "auth": "Bearer LONG-LIVED"}
        assert shim.handle("GET", "/core/api/../../etc", tokens["consumer"])[0] == 400
    finally:
        server.shutdown()


def test_http_listener_accepts_bearer_and_legacy_headers_and_refuses_foreign_peers(world):
    _, shim, _, tokens = world
    server = supervisor_api.make_server(shim, "127.0.0.1", 0, allow_any_peer=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        for header in ({"Authorization": "Bearer " + tokens["consumer"]}, {"X-Supervisor-Token": tokens["consumer"]},
                       {"X-Hassio-Key": tokens["consumer"]}):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/addons/self/options/config", headers=header)
            assert json.loads(urllib.request.urlopen(req, timeout=5).read())["data"] == {"a": 1}
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/info", timeout=5)
        assert err.value.code == 401
    finally:
        server.shutdown()
    strict = supervisor_api.make_server(shim, "127.0.0.1", 0)  # loopback is outside 172.30.32.0/23
    threading.Thread(target=strict.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{strict.server_address[1]}/info",
                                     headers={"Authorization": "Bearer " + tokens["consumer"]})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        assert err.value.code == 403
    finally:
        strict.shutdown()


def test_redirect_rule_is_checked_then_inserted_once_and_failures_are_reported():
    calls = []

    def fake(rc_check):
        def run(argv):
            calls.append(argv)
            return rc_check if "-C" in argv else 0
        return run
    assert supervisor_api.ensure_redirect(fake(0)) is True and len(calls) == 1 and "-C" in calls[0]
    calls.clear()
    assert supervisor_api.ensure_redirect(fake(1)) is True
    assert "-C" in calls[0] and "-I" in calls[1] and "PREROUTING" in calls[1]
    rule = " ".join(calls[1])
    assert "172.30.32.2" in rule and "--dport 80" in rule and f"--to-ports {supervisor_api.SHIM_PORT}" in rule and "opihaadd0" in rule
    assert supervisor_api.ensure_redirect(lambda argv: 1) is False

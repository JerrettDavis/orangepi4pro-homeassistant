from __future__ import annotations
import asyncio
import http.server
import json
import threading
import aiohttp
from aiohttp import web
import pytest
from opiha_apps import supervisor_api, supervisor_ws
from opiha_apps.common import AppError, write_json
from test_supervisor_api import world, call  # noqa: F401
from test_addon_manager import clean_registry  # noqa: F401


class FakeHA:
    """A real aiohttp WebSocket + REST server standing in for Home Assistant."""
    def __init__(self):
        self.seen_tokens, self.flow_posts = [], []
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()
        assert self.ready.wait(5)

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "auth_required", "ha_version": "2026.9.3"})
        auth = await ws.receive_json()
        self.seen_tokens.append(auth["access_token"])
        if auth["access_token"] != "LONG-LIVED-HA-TOKEN":
            await ws.send_json({"type": "auth_invalid"})
            return ws
        await ws.send_json({"type": "auth_ok", "ha_version": "2026.9.3"})
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                await ws.send_json({"id": data["id"], "type": "result", "success": True, "result": {"echo": data["type"], "pad": "x" * data.get("pad", 0)}})
        return ws

    SCHEMA = [  # shape captured from the real mqtt flow on the Orange Pi (HA 2026.9.3)
        {"name": "broker", "required": True, "selector": {"text": {}}},
        {"name": "port", "required": True, "default": 1883, "selector": {"number": {}}},
        {"name": "protocol", "required": True, "default": "5", "selector": {"select": {"options": ["5", "3.1.1", "3.1"]}}},
        {"name": "username", "required": False, "selector": {"text": {}}},
        {"name": "password", "required": False, "selector": {"text": {}}},
        {"type": "expandable", "name": "other_settings", "schema": [
            {"name": "set_client_cert", "required": True, "selector": {"boolean": {}}},
            {"name": "set_ca_cert", "required": True, "selector": {"select": {"options": ["off", "auto", "custom"]}}},
            {"name": "transport", "required": True, "default": "tcp", "selector": {"select": {"options": [{"value": "tcp"}]}}}]}]

    async def flow_start(self, request):
        assert request.headers["Authorization"] == "Bearer LONG-LIVED-HA-TOKEN"
        self.flow_posts.append(await request.json())
        return web.json_response({"type": "form", "flow_id": "f1", "step_id": "broker", "data_schema": self.SCHEMA})

    async def flow_step(self, request):
        body = await request.json()
        self.flow_posts.append(body)
        required = {"broker", "port", "protocol", "other_settings"}
        if required - set(body) or {"set_client_cert", "set_ca_cert", "transport"} - set(body.get("other_settings", {})):
            return web.json_response({"errors": {"base": ["required key not provided"]}}, status=400)
        return web.json_response({"type": "create_entry"})

    def run(self):
        asyncio.set_event_loop(self.loop)
        app = web.Application()
        app.router.add_get("/api/websocket", self.ws)
        app.router.add_post("/api/config/config_entries/flow", self.flow_start)
        app.router.add_post("/api/config/config_entries/flow/{id}", self.flow_step)
        runner = web.AppRunner(app)
        self.loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        self.loop.run_until_complete(site.start())
        self.port = site._server.sockets[0].getsockname()[1]
        self.ready.set()
        self.loop.run_forever()

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


@pytest.fixture
def ha(world, tmp_path):
    manager, shim, repo, tokens = world
    fake = FakeHA()
    write_json(tmp_path / "etc/appliance.json", {"mode": "appliance", "data_dir": str(tmp_path), "ha_version": "2026.9.3",
                                                  "ha_url": f"http://127.0.0.1:{fake.port}"})
    (manager.root / "ha-token").write_text("LONG-LIVED-HA-TOKEN\n")
    yield manager, shim, tokens, fake
    fake.stop()


def listener(shim):
    server = supervisor_api.make_server(shim, "127.0.0.1", 0, allow_any_peer=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def session(url, token, messages):
    out = []
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(url) as ws:
            out.append(await ws.receive_json())
            await ws.send_json({"type": "auth", "access_token": token})
            out.append(await ws.receive_json())
            for m in messages:
                await ws.send_json(m)
                out.append(await ws.receive_json(timeout=5))
    return out


def test_websocket_relay_authenticates_addon_and_swaps_in_the_ha_token(ha):
    manager, shim, tokens, fake = ha
    server = listener(shim)
    url = f"http://127.0.0.1:{server.server_address[1]}/core/websocket"
    try:
        out = asyncio.run(session(url, tokens["consumer"], [{"id": 1, "type": "get_states"}, {"id": 2, "type": "ping", "pad": 200000}]))
        assert out[0]["type"] == "auth_required" and out[1]["type"] == "auth_ok"
        assert out[2] == {"id": 1, "type": "result", "success": True, "result": {"echo": "get_states", "pad": ""}}
        assert len(out[3]["result"]["pad"]) == 200000  # a multi-frame-sized message survives the relay
        assert fake.seen_tokens == ["LONG-LIVED-HA-TOKEN"] and tokens["consumer"] not in fake.seen_tokens
    finally:
        server.shutdown()


@pytest.mark.parametrize("who", ["bad", "mosquitto"])
def test_websocket_relay_refuses_unknown_tokens_and_addons_without_ha_api(ha, who):
    manager, shim, tokens, fake = ha
    server = listener(shim)
    url = f"http://127.0.0.1:{server.server_address[1]}/core/websocket"
    try:
        out = asyncio.run(session(url, "0" * 64 if who == "bad" else tokens[who], []))
        assert out[1]["type"] == "auth_invalid" and not fake.seen_tokens
    finally:
        server.shutdown()


def test_websocket_without_a_configured_token_says_so(world):
    manager, shim, repo, tokens = world
    server = listener(shim)
    try:
        async def go():
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(f"http://127.0.0.1:{server.server_address[1]}/core/websocket") as ws:
                    return await ws.receive_json()
        assert "access token" in asyncio.run(go())["message"]
    finally:
        server.shutdown()


def test_frame_codec_roundtrip_with_masking():
    import socket
    a, b = socket.socketpair()
    for size in (0, 5, 125, 126, 70000):
        data = bytes(range(256)) * (size // 256) + bytes(size % 256)
        supervisor_ws.write_frame(a, True, 0x1, data, True)
        fin, op, got = supervisor_ws.read_frame(b)
        assert (fin, op, got) == (True, 0x1, data)
    a.close()
    b.close()


def test_mqtt_discovery_registers_the_broker_through_the_config_flow(ha):
    manager, shim, tokens, fake = ha
    status, payload = call(shim, "POST", "/discovery", tokens["mosquitto"],
                           {"service": "mqtt", "config": {"host": "core-mosquitto", "port": 1883, "username": "homeassistant", "password": "s3cret"}})
    assert status == 200 and payload["data"]["outcome"] == "created"
    assert fake.flow_posts[0]["handler"] == "mqtt"
    assert fake.flow_posts[1] == {"broker": "127.0.0.1", "port": 21883, "protocol": "5", "username": "homeassistant", "password": "s3cret",
                                  "other_settings": {"set_client_cert": False, "set_ca_cert": "off", "transport": "tcp"}}
    status, payload = call(shim, "POST", "/discovery", tokens["mosquitto"], {"service": "mqtt", "config": {"port": 9999}})
    assert status == 400 and "not published" in payload["message"]


def test_discovery_without_a_token_is_an_explicit_error(world):
    manager, shim, repo, tokens = world
    status, payload = call(shim, "POST", "/discovery", tokens["mosquitto"], {"service": "mqtt", "config": {"port": 1883}})
    assert status == 503 and "access token" in payload["message"]


def test_discovery_helper_rejects_hostile_broker_values():
    with pytest.raises(AppError):
        supervisor_ws.discover_mqtt("http://127.0.0.1:1", "t", "bad host;x", 1883, None, None)


def _declare(slug, service):
    from opiha_apps import catalog
    entry = catalog.entry(slug)
    entry["manifest"]["discovery"] = [service]
    catalog.register(slug, entry)


def test_wyoming_discovery_uses_the_addon_container_address(ha, monkeypatch):
    from conftest import execute
    manager, shim, tokens, fake = ha
    slug = [r for r in manager.records()][0]
    seen = {}

    def flow(ha_url, token, handler, supplied, menu_step=None):
        seen.update(handler=handler, supplied=supplied)
        return "created"
    monkeypatch.setattr(supervisor_ws, "discover_flow", flow)
    _declare(slug, "wyoming")
    assert execute(manager, slug, "start")["status"] == "succeeded"  # the fake engine puts it at 172.30.33.5
    status, payload = call(shim, "POST", "/discovery", tokens["mosquitto"], {"service": "wyoming", "config": {"uri": "tcp://core-piper:10200"}})
    assert status == 200 and payload["data"]["outcome"] == "created"
    assert seen == {"handler": "wyoming", "supplied": {"host": "172.30.33.5", "port": 10200}}
    with pytest.raises(AppError):
        supervisor_ws.discover_wyoming("http://127.0.0.1:1", "t", "172.30.33.5", "x")


def test_other_discovery_services_stay_explicitly_unimplemented(ha):
    manager, shim, tokens, fake = ha
    slug = [r for r in manager.records()][0]
    _declare(slug, "zwave_js")
    status, payload = call(shim, "POST", "/discovery", tokens["mosquitto"], {"service": "zwave_js", "config": {}})
    assert status == 501 and "Wyoming" in payload["message"]

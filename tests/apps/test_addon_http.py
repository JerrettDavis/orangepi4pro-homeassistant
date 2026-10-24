from __future__ import annotations
import asyncio
import types
import aiohttp
from aiohttp import web
import pytest
from conftest import wait
from test_addon_manager import MOSQ, make_repo, slug as slug_of, clean_registry  # noqa: F401
from test_http_component import api, component, http, Connection, FakeManagerClient  # noqa: F401


def test_store_routes_require_auth_and_validate(api, manager):
    url, token = api
    manager.ha_config = str(manager.root.parent / "ha")
    assert http(url, path="/v1/repos")[0] == 401
    status, body = http(url, token, "/v1/repos")
    assert status == 200 and body["repositories"] == [] and body["suggested"] and body["ha_token_configured"] is False
    assert http(url, token, "/v1/repos/add", {"url": "http://github.com/a/b"})[0] == 400
    assert http(url, token, "/v1/repos/add", {"url": "https://github.com/a/b", "x": 1})[0] == 400
    assert http(url, token, "/v1/repos/ZZZZZZZZ/addons")[0] == 404
    repo = make_repo(manager, {"mosquitto/config.yaml": MOSQ})
    status, body = http(url, token, "/v1/repos/" + repo + "/addons")
    assert status == 200 and body["addons"][0]["report"]["status"] == "reduced" or body["addons"][0]["report"]["status"] == "works"
    status, plan = http(url, token, "/v1/addon/plan", {"repository": repo, "folder": "mosquitto", "options": {"grants": ["ha_api"]}})
    assert status == 200 and plan["action"] == "install" and plan["privileges"] and not manager.engine.calls
    assert http(url, token, "/v1/addon/plan", {"repository": repo, "folder": "mosquitto", "evil": 1})[0] == 400
    assert http(url, token, "/v1/addon/plan", {"repository": repo, "folder": "../x"})[0] == 400
    status, applied = http(url, token, "/v1/apply", {"id": plan["id"], "confirm": True})
    assert status == 200 and wait(manager, applied)["status"] == "succeeded"
    assert http(url, token, "/v1/addons/ha-token", {"token": "short"})[0] == 400
    assert http(url, token, "/v1/addons/ha-token", {"token": "a" * 40})[1]["ha_token_configured"] is True
    mode = (manager.root / "ha-token").stat().st_mode & 0o777
    assert mode == 0o600
    assert http(url, token, "/v1/repos/remove", {"id": repo})[0] == 200


def test_ha_store_ws_boundary_and_contract(component):
    client = FakeManagerClient()
    hass = types.SimpleNamespace(data={"opiha_apps": {"client": client}})
    denied = Connection(False)
    asyncio.run(component.ws_store(hass, denied, {"id": 1, "operation": "repo_add", "data": {"url": "https://github.com/a/b"}}))
    assert denied.error[1] == "unauthorized" and not client.calls
    for operation, data in [("repos", {"x": 1}), ("repo_addons", {"id": "../x"}), ("repo_add", {"id": "abcdef12"}),
                            ("addon_plan", {"repository": "abcdef12"}), ("addon_plan", {"repository": "a", "folder": "b", "x": 1}),
                            ("ha_token", {"token": "t", "x": 1})]:
        bad = Connection()
        asyncio.run(component.ws_store(hass, bad, {"id": 2, "operation": operation, "data": data}))
        assert bad.error and not client.calls, operation
    good = Connection()
    asyncio.run(component.ws_store(hass, good, {"id": 3, "operation": "repo_add", "data": {"url": "https://github.com/a/b"}}))
    assert client.calls[0] == ("POST", "/v1/repos/add", {"url": "https://github.com/a/b"}, component.STORE_TIMEOUT)
    asyncio.run(component.ws_store(hass, Connection(), {"id": 4, "operation": "repo_addons", "data": {"id": "abcdef12"}}))
    assert client.calls[1][:2] == ("GET", "/v1/repos/abcdef12/addons")


def test_addon_ingress_strips_prefix_sets_ingress_path_and_refuses_foreign_hosts(component):
    async def scenario():
        from tested_opiha_component.ingress import Ingress, SessionView, PREFIX, valid_app
        assert valid_app("x97393e-configurator") and not valid_app("x97393e-../x") and not valid_app("evil")
        user = types.SimpleNamespace(id="admin-test", is_admin=True, is_active=True)
        refresh = types.SimpleNamespace(user=user)
        hass = types.SimpleNamespace(auth=types.SimpleNamespace(async_get_refresh_token=lambda v: refresh if v == "test-refresh" else None))
        seen = []

        async def backend(request):
            seen.append((request.path, dict(request.headers)))
            if request.path == "/redirect":
                return web.Response(status=302, headers={"Location": "/login"})
            return web.json_response({"path": request.path})
        upstream = web.Application()
        upstream.router.add_route("*", "/{tail:.*}", backend)
        runner = web.AppRunner(upstream)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        hosts = {"x97393e-configurator": "127.0.0.1", "x97393e-evil": "8.8.8.8"}

        class Descriptor:
            async def request(self, method, path, body=None):
                slug = path.split("/")[3]
                return {"app": slug, "port": port, "prefix": PREFIX + slug + "/", "host": hosts[slug], "strip_prefix": True, "entry": "index.html"}
        ingress = Ingress(hass, Descriptor())
        view = SessionView(ingress)

        async def mint(request):
            request["hass_user"], request["hass_refresh_token_id"] = user, "test-refresh"
            return await view.post(request)

        async def proxy(request):
            return await ingress.proxy(request, request.match_info["app"], request.match_info["tail"])
        app = web.Application()
        app.router.add_post("/api/opiha_apps/session", mint)
        app.router.add_route("*", PREFIX + "{app}/{tail:.*}", proxy)
        ar = web.AppRunner(app)
        await ar.setup()
        site2 = web.TCPSite(ar, "127.0.0.1", 0)
        await site2.start()
        base = "http://127.0.0.1:" + str(site2._server.sockets[0].getsockname()[1])
        try:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as client:
                async with client.post(base + "/api/opiha_apps/session", json={"app": "x97393e-evil"}) as res:
                    assert res.status == 502  # a descriptor naming a non-add-on address is refused
                async with client.post(base + "/api/opiha_apps/session", json={"app": "x97393e-configurator"}) as res:
                    assert res.status == 200
                    assert (await res.json())["url"] == PREFIX + "x97393e-configurator/index.html"
                async with client.get(base + PREFIX + "x97393e-configurator/files/a.txt") as res:
                    assert (await res.json())["path"] == "/files/a.txt"
                assert seen[-1][1]["X-Ingress-Path"] == PREFIX + "x97393e-configurator"
                async with client.get(base + PREFIX + "x97393e-configurator/redirect", allow_redirects=False) as res:
                    assert res.status == 302 and res.headers["Location"] == PREFIX + "x97393e-configurator/login"
        finally:
            await ingress.close()
            await ar.cleanup()
            await runner.cleanup()
    asyncio.run(scenario())

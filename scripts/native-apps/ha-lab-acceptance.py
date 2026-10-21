#!/usr/bin/env python3
"""Real Home Assistant authorization acceptance for the native Apps panel.

Run this against a DISPOSABLE Home Assistant (blank config, own port) that loads the
opiha_apps integration and points at a disposable manager. It creates an administrator
and a regular user, then checks the WebSocket command, session endpoint and ingress from
both. It never touches the production HA instance and only issues read-only/plan requests.
Use it from the HA image's Python (aiohttp is available there):

    python3 ha-lab-acceptance.py --ha http://127.0.0.1:18124
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
import aiohttp

PASSWORD = "lab-only-" + "x" * 24


class Failure(Exception):
    pass


def check(name: str, condition: bool, detail: str = ""):
    print(("PASS " if condition else "FAIL ") + name + (" - " + detail if detail and not condition else ""))
    if not condition:
        raise Failure(name)


async def token_for(http, base, client_id, code):
    async with http.post(base + "/auth/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id}) as r:
        return (await r.json())["access_token"]


async def login(http, base, client_id, username):
    async with http.post(base + "/auth/login_flow", json={"client_id": client_id, "handler": ["homeassistant", None], "redirect_uri": client_id}) as r:
        flow = await r.json()
    async with http.post(base + "/auth/login_flow/" + flow["flow_id"], json={"client_id": client_id, "username": username, "password": PASSWORD}) as r:
        result = await r.json()
    return await token_for(http, base, client_id, result["result"])


async def ws_call(http, base, token, message):
    async with http.ws_connect(base + "/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        auth = await ws.receive_json()
        check("websocket authenticates", auth["type"] == "auth_ok")
        await ws.send_json({"id": 1, **message})
        return await ws.receive_json()


async def main(base: str) -> int:
    client_id = base + "/"
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as http:
        async with http.post(base + "/api/onboarding/users", json={"client_id": client_id, "name": "Lab Admin", "username": "labadmin",
                                                                    "password": PASSWORD, "language": "en"}) as r:
            check("lab onboarding creates administrator", r.status == 200, str(r.status))
            admin_code = (await r.json())["auth_code"]
        admin = await token_for(http, base, client_id, admin_code)
        created = await ws_call(http, base, admin, {"type": "config/auth/create", "name": "Lab Regular", "group_ids": ["system-users"]})
        check("lab creates a non-admin user", created["success"], json.dumps(created)[:120])
        user_id = created["result"]["user"]["id"]
        made = await ws_call(http, base, admin, {"type": "config/auth_provider/homeassistant/create", "user_id": user_id,
                                                  "username": "labuser", "password": PASSWORD})
        check("lab credentials for non-admin", made["success"])
        regular = await login(http, base, client_id, "labuser")

        # WebSocket command authorization.
        for operation in ("overview", "metrics"):
            reply = await ws_call(http, base, admin, {"type": "opiha_apps/request", "operation": operation})
            check(f"admin websocket {operation}", reply["success"] and "apps" in reply["result"], json.dumps(reply)[:160])
        reply = await ws_call(http, base, regular, {"type": "opiha_apps/request", "operation": "overview"})
        check("regular user websocket denied", not reply["success"] and reply["error"]["code"] == "unauthorized", json.dumps(reply)[:160])
        reply = await ws_call(http, base, admin, {"type": "opiha_apps/request", "operation": "plan", "data": {"app": "nodered", "action": "remove"}})
        check("admin plan is validated by the manager", reply["success"] or reply["error"]["code"] == "native_apps_error")
        reply = await ws_call(http, base, admin, {"type": "opiha_apps/request", "operation": "plan",
                                                   "data": {"app": "nodered", "action": "install", "options": {"image": "evil/image"}}})
        check("arbitrary image option rejected", not reply["success"])
        reply = await ws_call(http, base, admin, {"type": "opiha_apps/request", "operation": "shell", "data": {}})
        check("unknown operation rejected", not reply["success"])

        # Session cookie endpoint.
        bearer = lambda t: {"Authorization": "Bearer " + t}
        async with http.post(base + "/api/opiha_apps/session", json={"app": "nodered"}) as r:
            check("session without HA login refused", r.status == 401, str(r.status))
        async with http.post(base + "/api/opiha_apps/session", json={"app": "nodered"}, headers=bearer(regular)) as r:
            check("session for regular user refused", r.status == 403, str(r.status))
        async with http.post(base + "/api/opiha_apps/session", json={"app": "unknown"}, headers=bearer(admin)) as r:
            check("session for unreviewed app refused", r.status in {400, 403}, str(r.status))
        overview = await ws_call(http, base, admin, {"type": "opiha_apps/request", "operation": "overview"})
        state = next(a["state"] for a in overview["result"]["apps"] if a["id"] == "nodered")
        url = base + "/api/opiha_apps/ingress/nodered/"
        async with http.get(url) as r:
            check("ingress without cookie refused", r.status in {401, 403}, str(r.status))
        async with http.post(url, headers={"Origin": "https://evil.example"}, data=b"{}") as r:
            check("cross-origin write without cookie refused", r.status in {401, 403}, str(r.status))
        async with http.post(base + "/api/opiha_apps/session", json={"app": "nodered"}, headers=bearer(admin)) as r:
            if state != "running":
                check("session refused while the app is not running", r.status == 503, f"{r.status} state={state}")
                print("SKIP cookie/ingress proxy checks: nodered is " + state + " (run again with it running)")
                cookie = ""
            else:
                check("session for admin issued", r.status == 200, str(r.status))
                cookie = r.headers.get("Set-Cookie", "")
                check("session cookie is HttpOnly and SameSite=Strict", "HttpOnly" in cookie and "SameSite=Strict" in cookie, cookie)
        if cookie:
            value = cookie.split(";", 1)[0]
            async with http.get(url, headers={"Cookie": value}) as r:
                check("ingress with cookie proxies the app", r.status == 200, str(r.status))
            async with http.post(url, headers={"Cookie": value, "Origin": "https://evil.example"}, data=b"{}") as r:
                check("cross-origin write with valid cookie refused", r.status == 403, str(r.status))
            async with http.post(url, headers={"Cookie": value}, data=b"{}") as r:
                check("write without Origin refused", r.status == 403, str(r.status))
            async with http.get(base + "/api/opiha_apps/ingress/nodered/..%2f..%2fapi", headers={"Cookie": value}) as r:
                check("path traversal refused", r.status in {400, 404}, str(r.status))
        async with http.get(base + "/api/opiha_apps/panel.js") as r:
            body = await r.text()
            check("panel script carries no bearer credential", "Bearer " not in body)
    print("RESULT all lab authorization checks passed")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ha", required=True, help="Disposable HA base URL, e.g. http://127.0.0.1:18124")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(main(args.ha.rstrip("/"))))
    except Failure:
        raise SystemExit(1)
